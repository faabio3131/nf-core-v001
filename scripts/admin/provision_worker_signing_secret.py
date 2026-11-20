"""Create one version of the Worker webhook-signing secret in the local vault.

Run on the host, as the uid that runs the Worker container (10001), e.g.:
  NFCORE_WORKER_LOCAL_VAULT_DIR=... NFCORE_WORKER_LOCAL_VAULT_KEY_BASE64=... \
  python provision_worker_signing_secret.py --tenant T --unit U --provider P \
      --reference sec_... --version 1 [--generate | --prompt]

--generate creates 48 random bytes and prints them ONCE (base64url) so the
webhook receiver can be configured; --prompt reads an existing secret hidden.
Files are never overwritten: rotation is a new --version.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets

from kordena_fiscal.security.secrets import SecretReference, SecretScope
from kordena_fiscal.vault.local_signing_vault import LocalSigningVault


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--version", type=int, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--prompt", action="store_true")
    args = parser.parse_args()
    vault = LocalSigningVault(
        directory=os.environ["NFCORE_WORKER_LOCAL_VAULT_DIR"],
        master_key=base64.b64decode(
            os.environ["NFCORE_WORKER_LOCAL_VAULT_KEY_BASE64"], validate=True,
        ),
    )
    if args.generate:
        value = secrets.token_bytes(48)
    else:
        typed = getpass.getpass("Segredo de assinatura (não aparece): ")
        value = typed.encode("utf-8")
    path = vault.store(
        SecretReference(args.reference, args.version),
        SecretScope(args.tenant, args.unit, "webhook-signing"),
        args.provider, value,
    )
    print(f"gravado: {path.name} (0600)")
    if args.generate:
        print("Segredo (mostrado UMA vez, copie para o receptor do webhook):")
        print(base64.urlsafe_b64encode(value).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
