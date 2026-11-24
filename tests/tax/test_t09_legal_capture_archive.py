"""T09 archive verifier: reproducible byte identity and fail-closed semantics."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from runpy import run_path

import pytest

MODULE = run_path(
    str(Path(__file__).resolve().parents[2]
        / "scripts/nfcore_t09_verify_legal_capture_archive.py"),
    run_name="t09_archive_verifier_test",
)
verify_archive = MODULE["verify_archive"]


def _fixture(tmp_path: Path, *, alteration: str = "") -> tuple[Path, dict]:
    files = []
    archive = tmp_path / "evidence.zip"
    for i in range(50):
        uf = "SP" if i % 2 else "PI"
        name = f"evidence_{i:02d}.html"
        source = f"authority is not certified: {i}".encode()
        files.append({
            "uf": uf,
            "nome": name,
            "bytes": len(source),
            "sha256": hashlib.sha256(source).hexdigest(),
        })

    inside = []
    for row in files:
        inside.append({
            **row,
            "fonte_primaria_autenticada": alteration == "false_primary",
            "curadoria_aceita": False,
            "importacao_permitida": False,
        })
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr(
            "NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json",
            json.dumps({"arquivos": inside}),
        )
        for i, item in enumerate(files):
            data = f"authority is not certified: {i}".encode()
            if alteration == "tampered_bytes" and i == 10:
                data = b"tampered"
            bundle.writestr(
                f"capturas_recentes/{item['uf']}/{item['nome']}",
                data,
            )
        if alteration == "extra_capture":
            bundle.writestr("capturas_recentes/PI/hidden.html", b"outside manifest")
        if alteration == "unsafe_path":
            bundle.writestr("../escape.txt", b"bad path")
    archive.write_bytes(stream.getvalue())
    receipt = {
        "files": files,
        "consolidated_archive": {
            "sha256": hashlib.sha256(stream.getvalue()).hexdigest(),
        },
    }
    if alteration == "wrong_archive_sha":
        receipt["consolidated_archive"]["sha256"] = "0" * 64
    return archive, receipt


def test_50_captures_are_reproducible_but_not_fiscally_approved(tmp_path):
    archive, receipt = _fixture(tmp_path)
    outcome = verify_archive(archive, receipt)
    assert outcome["evidence_files_verified"] == 50
    assert outcome["integrity"] == "PASS"
    assert outcome["authenticity_of_official_publication_certified"] is False
    assert outcome["normative_curation_certified"] is False
    assert outcome["fiscal_import_authorized"] is False


@pytest.mark.parametrize("alteration,reason", [
    ("tampered_bytes", "evidence corrupted"),
    ("wrong_archive_sha", "archive SHA-256 mismatch"),
    ("extra_capture", "unmanifested/absent"),
    ("unsafe_path", "unsafe ZIP entry"),
    ("false_primary", "false legal source authentication"),
])
def test_corrupted_or_false_evidence_cannot_be_accepted(tmp_path, alteration, reason):
    archive, receipt = _fixture(tmp_path, alteration=alteration)
    with pytest.raises(ValueError, match=reason):
        verify_archive(archive, receipt)


def test_git_receipt_cannot_fake_source_size_or_digest(tmp_path):
    archive, receipt = _fixture(tmp_path)
    receipt["files"][0]["bytes"] = 123456
    with pytest.raises(ValueError, match="archive receipt mismatch"):
        verify_archive(archive, receipt)
