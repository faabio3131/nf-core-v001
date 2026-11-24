"""Pinned sale configuration selected by authenticated fiscal scope, never a path from HTTP."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from kordena_fiscal.domain import ExecutionScope, FiscalDocumentKind, FiscalValidationError
from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions

from .sale_facts import _unique, parse_sale_rule


def sale_policy_key(scope: ExecutionScope, kind: FiscalDocumentKind) -> str:
    return hashlib.sha256(json.dumps([*scope.identity_material, kind.value]).encode()).hexdigest()


def load_sale_policy(
    environ: Mapping[str, str],
    scope: ExecutionScope,
    kind: FiscalDocumentKind,
) -> tuple[dict[str, Any], str, bytes]:
    """Load a current reviewed policy; legacy interstate decisions cannot authorize sales."""
    return _load_sale_policy(environ, scope, kind, require_reviewed_destination=True)


def _load_sale_policy(
    environ: Mapping[str, str],
    scope: ExecutionScope,
    kind: FiscalDocumentKind,
    *,
    require_reviewed_destination: bool,
) -> tuple[dict[str, Any], str, bytes]:
    """Validate the scoped, checksum-pinned policy bounded to 1 MiB."""
    try:
        root = Path(environ.get("NFCORE_SALE_FISCAL_POLICY_ROOT", ""))
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("policy root unavailable")
        filename = sale_policy_key(scope, kind)
        path, pin = root / (filename + ".json"), root / (filename + ".sha256")
        if path.is_symlink() or pin.is_symlink():
            raise ValueError("policy symlink")
        with pin.open("rb") as stream:
            digest = stream.read(66)
        if not re.fullmatch(rb"[0-9a-f]{64}\n?", digest):
            raise ValueError("invalid pin")
        expected = digest.decode().strip()
        with path.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("policy integrity")
        policy = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(policy, dict) or set(policy) != {
            "schema_version",
            "policy_id",
            "version",
            "host_namespace",
            "tenant_id",
            "unit_id",
            "environment",
            "document_kind",
            "issuer_profile_id",
            "issuer_profile_version",
            "products",
            "series",
            "sale_options",
            "rules",
        }:
            raise ValueError("policy fields")
        if (
            any(
                type(policy[k]) is not int or policy[k] < 1
                for k in ("schema_version", "version", "issuer_profile_version")
            )
            or policy["schema_version"] != 1
            or any(
                not isinstance(policy[k], str) or not 1 <= len(policy[k]) <= 128
                for k in ("policy_id", "issuer_profile_id")
            )
            or policy["host_namespace"] != scope.host_namespace
            or policy["tenant_id"] != scope.tenant_id
            or policy["unit_id"] != scope.unit_id
            or policy["environment"] != scope.environment.value
            or policy["document_kind"] != kind.value
            or kind not in {FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE}
            or type(policy["series"]) is not int
            or not 0 <= policy["series"] <= 999
        ):
            raise ValueError("policy scope or version")
        products = policy["products"]
        if not isinstance(products, dict) or not 1 <= len(products) <= 500:
            raise ValueError("product bindings required")
        for product_id, binding in products.items():
            if (
                not isinstance(product_id, str)
                or not 1 <= len(product_id) <= 128
                or not isinstance(binding, dict)
                or set(binding) != {"version"}
                or type(binding["version"]) is not int
                or binding["version"] < 1
            ):
                raise ValueError("product binding")
        if not isinstance(policy["rules"], list) or not 1 <= len(policy["rules"]) <= 500:
            raise ValueError("rules required")
        for rule in policy["rules"]:
            parsed = parse_sale_rule(rule, document_kind=kind)
            rates = parsed.outcome.nfe_rates
            if rates is not None and rates.icms_benefit is not None:
                if rates.icms_benefit.benefit_id is None:
                    raise ValueError("canonical T14 benefit identifier required")
            origin = parsed.selector.state_code
            destination = parsed.selector.destination_state_code
            if require_reviewed_destination and parsed.outcome.cfop.startswith("6") and (
                origin is None or destination is None or destination == origin
            ):
                raise ValueError("interstate sale rule requires exact reviewed destination")
            if destination is not None and (
                origin is None
                or parsed.outcome.cfop[0] != ("5" if origin == destination else "6")
                or (kind is FiscalDocumentKind.NFCE and destination != origin)
            ):
                raise ValueError("sale CFOP or model differs from reviewed destination")
        NfeSaleOptions(**policy["sale_options"])
        return policy, expected, raw
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError, RecursionError):
        raise FiscalValidationError("Scoped sale policy unavailable or invalid") from None


@contextmanager
def _serialized_policy_install(directory: Path, name: str) -> Iterator[None]:
    """Serialize same-scope policy promotions across processes on the host.

    Without a shared lock, a lower-version writer can overwrite a higher one
    after both have checked the previous version. Readers still fail closed
    while the signed JSON/SHA pair is replaced.
    """
    import fcntl
    import os
    import stat

    fd = os.open(
        directory / (name + ".lock"),
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise FiscalValidationError("Unsafe scoped fiscal policy install lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def install_reviewed_policy(source: Path, directory: Path) -> str:
    """Validate an operator-reviewed artifact and atomically replace its scoped pair.

    This function never invents rules/rates or changes issuer/product profiles.
    Readers reject the brief digest mismatch during replacement; no permissive
    fallback exists. Published versions already used by a sale remain immutable.
    """
    import os
    import tempfile
    from uuid import uuid4

    from kordena_fiscal.domain import FiscalEnvironment

    if source.is_symlink() or directory.is_symlink() or not directory.is_absolute():
        raise FiscalValidationError("Policy installation paths must be explicit and non-symlink")
    with source.open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise FiscalValidationError("Sale policy exceeds size limit")
    policy = json.loads(raw, object_pairs_hook=_unique)
    scope = ExecutionScope(policy["tenant_id"], policy["unit_id"],
        FiscalEnvironment(policy["environment"]), "policy-install", policy["host_namespace"])
    kind = FiscalDocumentKind(policy["document_kind"])
    name = sale_policy_key(scope, kind)
    digest = hashlib.sha256(raw).hexdigest()
    with tempfile.TemporaryDirectory(prefix="nfcore-policy-check-") as work:
        folder = Path(work)
        (folder / (name + ".json")).write_bytes(raw)
        (folder / (name + ".sha256")).write_text(digest, encoding="ascii")
        load_sale_policy({"NFCORE_SALE_FISCAL_POLICY_ROOT": work}, scope, kind)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise FiscalValidationError("Sale policy directory cannot be a symlink")
    with _serialized_policy_install(directory, name):
        target, pin = directory / (name + ".json"), directory / (name + ".sha256")
        if target.is_symlink() or pin.is_symlink():
            raise FiscalValidationError("Policy destination cannot be a symlink")
        if target.exists() or pin.exists():
            if not target.is_file() or not pin.is_file():
                raise FiscalValidationError("Existing sale policy installation is incomplete")
            # A valid legacy artifact can be read ONLY as the last installed
            # version, so its corrected successor can be promoted. Runtime and
            # incoming artifacts continue to require the new destination gate.
            previous, previous_digest, previous_raw = _load_sale_policy(
                {"NFCORE_SALE_FISCAL_POLICY_ROOT": str(directory)}, scope, kind,
                require_reviewed_destination=False,
            )
            if previous_digest == digest and previous_raw == raw:
                return name
            if policy["version"] <= previous["version"]:
                raise FiscalValidationError(
                    "Sale policy changes require a higher reviewed version"
                )
        suffix = "." + uuid4().hex + ".tmp"
        staged = directory / (name + suffix)
        staged_pin = directory / (name + suffix + ".sha256")
        try:
            staged.write_bytes(raw)
            staged_pin.write_text(digest + "\n", encoding="ascii")
            staged.chmod(0o644)
            staged_pin.chmod(0o644)
            os.replace(staged, target)
            os.replace(staged_pin, pin)
        finally:
            staged.unlink(missing_ok=True)
            staged_pin.unlink(missing_ok=True)
    return name


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Install reviewed native-sale fiscal policy")
    parser.add_argument("source", type=Path)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        name = install_reviewed_policy(args.source, args.directory)
    except (OSError, FiscalValidationError, KeyError, TypeError, ValueError) as exc:
        parser.exit(2, f"Policy was not installed: {type(exc).__name__}\n")
    print(f"Validated scoped policy installed: {name}")


if __name__ == "__main__":
    main()
