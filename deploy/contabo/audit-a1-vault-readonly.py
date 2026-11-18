#!/usr/bin/env python3
"""Auditoria somente leitura do cofre A1 efetivo no host Contabo.

Não abre certificados, não decripta A1, não imprime valores de ambiente,
identificadores internos, nomes de arquivos, paths, chaves ou senhas.
Não efetua alterações na VPS, Docker, PostgreSQL nem rede.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

CONTAINER = "nfcore-api"
_DEPLOY_MARKER = Path("/opt/fm/nfcore/.deployed")


def _docker(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["docker", *args], check=False, capture_output=True,
            text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _yes(value: object) -> str:
    return "SIM" if value else "NAO"


def _key_format_is_valid(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (ValueError, binascii.Error):
        return False


def _path_under(path: str, mount: str) -> bool:
    p, m = PurePosixPath(path), PurePosixPath(mount)
    return m != PurePosixPath("/") and (p == m or m in p.parents)


# Read-only probes; output contains no paths or file names.
_CONTAINER_PROBE = """
import json, os, pathlib, stat
root = os.environ.get('NFCORE_A1_VAULT_DIR')
if not root:
    print(json.dumps({'directory_present':False, 'record_count':0,
                      'record_permissions_ok':False, 'directory_permissions_ok':False}))
else:
    p = pathlib.Path(root)
    valid = p.is_dir() and not p.is_symlink()
    records = list(p.glob('*.a1.enc')) if valid else []
    ok_records = all(
        f.is_file() and not f.is_symlink()
        and stat.S_IMODE(f.stat().st_mode) & 0o077 == 0
        for f in records
    )
    ok_directory = valid and stat.S_IMODE(p.stat().st_mode) & 0o077 == 0
    print(json.dumps({'directory_present':valid, 'record_count':len(records),
                      'record_permissions_ok':ok_records,
                      'directory_permissions_ok':ok_directory}))
"""


def _pinned_production_sha(expected: str) -> bool:
    if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
        return False
    try:
        return _DEPLOY_MARKER.read_text(encoding="ascii").strip() == f"SHA={expected}"
    except (OSError, UnicodeError):
        return False


def main(expected_sha: str | None = None) -> int:
    if expected_sha is not None:
        if not _pinned_production_sha(expected_sha):
            print("DEPLOY_SHA_EXACT=BLOCKED")
            return 2
        print("DEPLOY_SHA_EXACT=PASS")
    else:
        print("DEPLOY_SHA_EXACT=NAO_VERIFICADO")
    raw = _docker(["inspect", CONTAINER])
    if raw is None:
        print("A1_AUDIT=INCONCLUSIVO; MOTIVO=CONTAINER_INACESSIVEL")
        return 3
    try:
        info = json.loads(raw)[0]
        env: dict[str, str] = {}
        for raw_pair in info["Config"].get("Env", []):
            if "=" in raw_pair:
                key, value = raw_pair.split("=", 1)
                env[key] = value
        root = env.get("NFCORE_A1_VAULT_DIR")
        key_is_valid = _key_format_is_valid(env.get("NFCORE_A1_VAULT_KEY_BASE64"))
        mounts = info.get("Mounts") or []
        persistent = False
        if isinstance(root, str) and root:
            persistent = any(
                mount.get("Type") in ("bind", "volume")
                and mount.get("RW") is True
                and isinstance(mount.get("Destination"), str)
                and _path_under(root, mount["Destination"])
                for mount in mounts
            )
        running = info.get("State", {}).get("Running") is True
        raw_probe = _docker(["exec", CONTAINER, "python", "-c", _CONTAINER_PROBE])
        probe = json.loads(raw_probe) if raw_probe is not None else None
        if not isinstance(probe, dict):
            probe = None
    except (ValueError, TypeError, KeyError, IndexError):
        print("A1_AUDIT=INCONCLUSIVO; MOTIVO=DOCKER_INSPECT_INCONSISTENTE")
        return 3

    print("AUDITORIA_A1=LEITURA_APENAS")
    print("API_CONTAINER_EM_EXECUCAO=" + _yes(running))
    print("VAULT_DIR_CONFIGURADO=" + _yes(bool(root)))
    print("CHAVE_MESTRA_FORMATO_32_BYTES=" + _yes(key_is_valid))
    print("MOUNT_PERSISTENTE_DECLARADO=" + _yes(persistent))
    def _probe_flag(field: str) -> str:
        return _yes(probe.get(field)) if probe else "NAO_VERIFICADO"

    print("DIRETORIO_ACESSIVEL=" + _probe_flag("directory_present"))
    print("DIRETORIO_PERMISSOES_RESTRITAS=" + _probe_flag("directory_permissions_ok"))
    print("ARQUIVOS_PERMISSOES_RESTRITAS=" + _probe_flag("record_permissions_ok"))
    print("ARQUIVOS_A1_CIFRADOS_PRESENTES=" + (
        "SIM" if probe and probe.get("record_count", 0) > 0
        else "NAO" if probe else "NAO_VERIFICADO"
    ))
    print("CERTIFICADO_DA_SISTEM_RECUPERAVEL=NAO_VERIFICADO")
    print("BACKUP_EXTERNO_COFRE=NAO_VERIFICADO")
    print("BACKUP_CHAVE_FORA_DA_VPS=NAO_VERIFICADO")
    print("RESTORE_ISOLADO_COFRE=NAO_VERIFICADO")
    if not (running and root and key_is_valid and persistent
            and probe and probe.get("directory_present")
            and probe.get("directory_permissions_ok")
            and probe.get("record_permissions_ok")):
        print("A1_VAULT_INFRA_GATE=REPROVADO_OU_INCONCLUSIVO")
        return 2
    print("A1_VAULT_INFRA_GATE=PRECHECK_LOCAL_PARCIAL")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A1 encrypted Vault read-only audit")
    parser.add_argument("--expected-production-sha", default=None)
    args = parser.parse_args()
    sys.exit(main(args.expected_production_sha))
