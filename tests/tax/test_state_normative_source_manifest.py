"""T09 importer binds legal source SHA256 to locally read bytes before DB writes."""
import hashlib
import json

import pytest

from scripts.nfcore_state_benefits_import_reviewed import (
    SOURCE_MANIFEST_SCHEMA,
    verify_reviewed_source_bytes,
)

URL = "https://legislacao.fazenda.sp.gov.br/Paginas/an3art041.aspx"


def packet(tmp_path):
    data = b"fake law for SOURCE-INTEGRITY UNIT TEST only"
    source = tmp_path / "decreto.html"
    source.write_bytes(data)
    policy = {"legal_citations": [{
        "source_url": URL, "source_sha256": hashlib.sha256(data).hexdigest(),
    }]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "sources": [{"source_url": URL, "relative_path": "decreto.html"}],
    }), encoding="utf-8")
    return policy, manifest, source


def test_reviewed_source_bytes_matching_digest_passes(tmp_path):
    policy, manifest, _ = packet(tmp_path)
    assert verify_reviewed_source_bytes(policy, manifest) == 1


def test_tampered_legal_source_bytes_fail_closed(tmp_path):
    policy, manifest, source = packet(tmp_path)
    source.write_bytes(b"different content")
    with pytest.raises(ValueError, match="bytes do not match"):
        verify_reviewed_source_bytes(policy, manifest)


def test_forged_source_hash_fails_closed(tmp_path):
    policy, manifest, _ = packet(tmp_path)
    policy["legal_citations"][0]["source_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="bytes do not match"):
        verify_reviewed_source_bytes(policy, manifest)


def test_unlisted_or_duplicate_legal_source_rejected(tmp_path):
    policy, manifest, _ = packet(tmp_path)
    packet_data = json.loads(manifest.read_text())
    packet_data["sources"].append(packet_data["sources"][0])
    manifest.write_text(json.dumps(packet_data))
    with pytest.raises(ValueError, match="manifest"):
        verify_reviewed_source_bytes(policy, manifest)


@pytest.mark.parametrize(
    "unsafe_path", ["../out.html", "/etc/passwd", "a/../../b", "C:\\temp\\doc"],
)
def test_legal_source_path_traversal_rejected(tmp_path, unsafe_path):
    policy, manifest, _ = packet(tmp_path)
    data = json.loads(manifest.read_text())
    data["sources"][0]["relative_path"] = unsafe_path
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unsafe|mapping"):
        verify_reviewed_source_bytes(policy, manifest)


def test_symlinked_legal_source_rejected(tmp_path):
    policy, manifest, source = packet(tmp_path)
    link = tmp_path / "shortcut.html"
    link.symlink_to(source)
    data = json.loads(manifest.read_text())
    data["sources"][0]["relative_path"] = "shortcut.html"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="symlinked"):
        verify_reviewed_source_bytes(policy, manifest)


def test_missing_source_file_rejected(tmp_path):
    policy, manifest, source = packet(tmp_path)
    source.unlink()
    with pytest.raises(FileNotFoundError):
        verify_reviewed_source_bytes(policy, manifest)
