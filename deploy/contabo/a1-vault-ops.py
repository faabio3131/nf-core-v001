#!/usr/bin/env python3
"""Back up encrypted A1 records to a separately encrypted, remote restic repository.

Host-only. Never reads/decrypts A1 private keys, PFX passwords or the A1 master
key. A different, offline recovery channel MUST escrow that key. No restore
ever writes to the live Vault. Remote repository readiness is not proof of
off-VPS storage or key escrow without independently inspected host evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_VAULT_UID = 10001
_REMOTE_PREFIXES = ("sftp:", "s3:", "b2:", "azure:", "gs:", "swift:", "rclone:", "rest:https://")
_RECORD = re.compile(r"[a-f0-9]{64}\.a1\.enc\Z")


class VaultOpsError(Exception):
    """Reject a backup/restore operation without exposing filesystem paths."""


def _vault_records() -> tuple[Path, dict[str, str]]:
    raw = os.environ.get("NFCORE_A1_VAULT_HOST_DIR", "")
    root = Path(raw)
    if not raw or not root.is_absolute() or root == Path("/") or root.is_symlink():
        raise VaultOpsError()
    try:
        metadata = root.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != _VAULT_UID:
            raise VaultOpsError()
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise VaultOpsError()
        records: dict[str, str] = {}
        for entry in root.iterdir():
            if entry.is_symlink() or not _RECORD.fullmatch(entry.name):
                raise VaultOpsError()
            details = entry.stat()
            if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077:
                raise VaultOpsError()
            records[entry.name] = hashlib.sha256(entry.read_bytes()).hexdigest()
        return root, records
    except OSError:
        raise VaultOpsError() from None


def _remote_config() -> None:
    repository = os.environ.get("RESTIC_REPOSITORY", "")
    password_path = os.environ.get("RESTIC_PASSWORD_FILE", "")
    if not repository.startswith(_REMOTE_PREFIXES) or not password_path:
        raise VaultOpsError()
    password_file = Path(password_path)
    if not password_file.is_absolute() or password_file.is_symlink():
        raise VaultOpsError()
    try:
        st = password_file.stat()
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
            raise VaultOpsError()
    except OSError:
        raise VaultOpsError() from None


def _restic(*args: str) -> None:
    try:
        result = subprocess.run(
            ["restic", *args], check=False, capture_output=True,
            timeout=3600, text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise VaultOpsError() from None
    if result.returncode != 0:
        # Never echo restic stdout/stderr: remote URLs and paths can be sensitive.
        raise VaultOpsError()


def backup() -> int:
    root, records = _vault_records()
    _remote_config()
    _restic("backup", "--quiet", "--tag", "nfcore-a1-vault", str(root))
    _restic("check", "--quiet")
    print(f"A1_REMOTE_BACKUP=SUCCESS; ENCRYPTED_RECORDS={len(records)}; KEY_ESCROW=NOT_VERIFIED")
    return 0


def restore_rehearsal() -> int:
    root, expected = _vault_records()
    _remote_config()
    stage = Path(tempfile.mkdtemp(prefix="nfcore-a1-restore-"))
    try:
        os.chmod(stage, 0o700)
        _restic(
            "restore", "latest", "--tag", "nfcore-a1-vault",
            "--quiet", "--target", str(stage),
        )
        restored_root = stage / root.relative_to("/")
        if restored_root.is_symlink() or not restored_root.is_dir():
            raise VaultOpsError()
        restored: dict[str, str] = {}
        for entry in restored_root.iterdir():
            if entry.is_symlink() or not _RECORD.fullmatch(entry.name) or not entry.is_file():
                raise VaultOpsError()
            restored[entry.name] = hashlib.sha256(entry.read_bytes()).hexdigest()
        if restored != expected:
            raise VaultOpsError()
        print(
            f"A1_ISOLATED_RESTORE=SUCCESS; ENCRYPTED_RECORDS={len(expected)}; "
            "KEY_ESCROW=NOT_VERIFIED"
        )
        return 0
    finally:
        shutil.rmtree(stage)



# Manual, dependency-free OFFLINE transport of the already AES-GCM-encrypted
# A1 records. A ZIP is NOT independently password-encrypted: secrecy and
# authenticity depend on the *separately escrowed* AES-GCM Vault key.
_OFFLINE_FORMAT = "nfcore-a1-ciphertexts-v1"
_OFFLINE_MAX_RECORDS = 4096
_OFFLINE_MAX_RECORD_BYTES = 6 * 1024 * 1024


def offline_export(archive: str) -> int:
    """Create an immutable ciphertext-only archive for owner-managed offsite copy.

    This is an export, NOT proof that the owner copied anything outside the VPS.
    Reject empty Vaults so a zero-record snapshot never gets labeled protected.
    """
    root, hashes = _vault_records()
    if not hashes or len(hashes) > _OFFLINE_MAX_RECORDS:
        raise VaultOpsError()
    target = Path(archive)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise VaultOpsError()
    parent = target.parent
    try:
        st = parent.stat()
        if parent.is_symlink() or not stat.S_ISDIR(st.st_mode):
            raise VaultOpsError()
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise VaultOpsError()
        if root.resolve() == parent.resolve() or root.resolve() in parent.resolve().parents:
            raise VaultOpsError()
        fd, temporary = tempfile.mkstemp(prefix=".a1-export-", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            entries = []
            with os.fdopen(fd, "wb") as output:
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as zf:
                    for name, digest in sorted(hashes.items()):
                        payload = (root / name).read_bytes()
                        if (len(payload) < 34 or len(payload) > _OFFLINE_MAX_RECORD_BYTES
                                or not payload.startswith(b"NFA1\x01")
                                or hashlib.sha256(payload).hexdigest() != digest):
                            raise VaultOpsError()
                        zf.writestr("records/" + name, payload)
                        entries.append({"name": name, "sha256": digest, "size": len(payload)})
                    zf.writestr("manifest.json", json.dumps({
                        "format": _OFFLINE_FORMAT, "records": entries,
                    }, sort_keys=True, separators=(",", ":")))
                output.flush()
                os.fsync(output.fileno())
            # Atomic no-clobber: refuse to replace an older recovery point.
            os.link(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except (OSError, ValueError, zipfile.BadZipFile):
        raise VaultOpsError() from None
    print(f"A1_OFFLINE_EXPORT=READY; ENCRYPTED_RECORDS={len(hashes)}; OFFSITE=NOT_VERIFIED")
    return 0


def _extract_offline(archive: Path, stage: Path) -> int:
    """Restore ONLY into caller-supplied isolated directory, never the live Vault."""
    if archive.is_symlink() or not archive.is_file() or not stage.is_dir():
        raise VaultOpsError()
    if any(stage.iterdir()):
        raise VaultOpsError()
    try:
        with zipfile.ZipFile(archive) as zf:
            items = zf.infolist()
            names = [item.filename for item in items]
            if (len(names) != len(set(names)) or len(names) < 2
                    or len(names) > _OFFLINE_MAX_RECORDS + 1
                    or names.count("manifest.json") != 1):
                raise VaultOpsError()
            for item in items:
                filename = item.filename
                mode = stat.S_IFMT(item.external_attr >> 16)
                if (mode not in (0, stat.S_IFREG)
                        or item.compress_type != zipfile.ZIP_STORED
                        or item.file_size > _OFFLINE_MAX_RECORD_BYTES
                        or (filename != "manifest.json" and (
                            not filename.startswith("records/")
                            or not _RECORD.fullmatch(filename[len("records/") :])
                        ))):
                    raise VaultOpsError()
            manifest_file = zf.getinfo("manifest.json")
            if manifest_file.file_size > 1024 * 1024:
                raise VaultOpsError()
            manifest = json.loads(zf.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != _OFFLINE_FORMAT:
                raise VaultOpsError()
            entries = manifest.get("records")
            if not isinstance(entries, list) or not 1 <= len(entries) <= _OFFLINE_MAX_RECORDS:
                raise VaultOpsError()
            expected_names = {"manifest.json"}
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"name", "sha256", "size"}:
                    raise VaultOpsError()
                name, digest, size = entry["name"], entry["sha256"], entry["size"]
                if (not isinstance(name, str) or not _RECORD.fullmatch(name)
                        or not isinstance(digest, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", digest)
                        or not isinstance(size, int)
                        or not 34 <= size <= _OFFLINE_MAX_RECORD_BYTES):
                    raise VaultOpsError()
                expected_names.add("records/" + name)
                payload = zf.read("records/" + name)
                if (len(payload) != size or not payload.startswith(b"NFA1\x01")
                        or hashlib.sha256(payload).hexdigest() != digest):
                    raise VaultOpsError()
                destination = stage / name
                # Fail closed on duplicate records, never open outside stage.
                with destination.open("xb") as output:
                    os.chmod(destination, 0o600)
                    output.write(payload)
            if expected_names != set(names) or len(expected_names) != len(names):
                raise VaultOpsError()
            return len(entries)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
        raise VaultOpsError() from None


def offline_restore_test(archive: str) -> int:
    """Isolated checksum/readback rehearsal; does not authenticate A1 without key."""
    with tempfile.TemporaryDirectory(prefix="nfcore-a1-offline-") as directory:
        stage = Path(directory)
        os.chmod(stage, 0o700)
        count = _extract_offline(Path(archive), stage)
        print(
            f"A1_OFFLINE_RESTORE=CHECKSUM_PASS; ENCRYPTED_RECORDS={count}; "
            "AES_GCM_READBACK=NOT_VERIFIED"
        )
    return 0


def main() -> int:
    try:
        if len(sys.argv) == 2 and sys.argv[1] in {"backup", "restore-test"}:
            return backup() if sys.argv[1] == "backup" else restore_rehearsal()
        if len(sys.argv) == 3 and sys.argv[1] in {"offline-export", "offline-restore-test"}:
            return (offline_export(sys.argv[2]) if sys.argv[1] == "offline-export"
                    else offline_restore_test(sys.argv[2]))
        raise VaultOpsError()
    except (VaultOpsError, OSError, ValueError):
        print("A1_VAULT_OPERATION=NOT_CERTIFIED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
