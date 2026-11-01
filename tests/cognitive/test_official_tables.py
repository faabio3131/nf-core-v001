from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kordena_fiscal.cognitive import composition, default_baselines
from kordena_fiscal.cognitive.knowledge import CatalogKind
from kordena_fiscal.cognitive.knowledge.official import (
    OFFICIAL_DIR,
    OfficialTablesError,
    load_official_catalog,
    read_manifest,
)
from kordena_fiscal.security.human_identity import HumanIdentityService

from .test_classification import cls_request, texts


@pytest.fixture(scope="module")
def catalog():  # type: ignore[no-untyped-def]
    return load_official_catalog()


def test_official_tables_load_with_manifest_counts(catalog) -> None:  # type: ignore[no-untyped-def]
    manifest = read_manifest()
    assert len(catalog.entries(CatalogKind.NCM)) == manifest["ncm"]["rows"] == 10516
    assert len(catalog.entries(CatalogKind.CCLASSTRIB)) == manifest["cclasstrib"]["rows"] == 170
    # seed catalogs are preserved next to the official ones
    assert catalog.lookup(CatalogKind.CST_ICMS, "00") is not None
    assert "official[ncm:" in catalog.version
    assert manifest["ncm"]["source_url"].startswith("https://portalunico.siscomex.gov.br/")
    assert manifest["cclasstrib"]["source_version"]["ambiente"]  # pilot environment is declared


def test_official_lookups_and_review_status(catalog) -> None:  # type: ignore[no-untyped-def]
    ncm = catalog.lookup(CatalogKind.NCM, "01012100")
    assert ncm is not None and "raça pura" in ncm.description
    assert catalog.lookup(CatalogKind.NCM, "99999999") is None
    cclass = catalog.lookup(CatalogKind.CCLASSTRIB, "000001")
    assert cclass is not None and "CST 000" in cclass.description
    # official origin + integrity do not replace human normative review
    assert catalog.review_status(CatalogKind.NCM).value == "pending_normative_review"


def copy_dir(tmp_path: Path) -> Path:
    target = tmp_path / "official"
    shutil.copytree(OFFICIAL_DIR, target)
    return target


def test_tampered_table_is_refused(tmp_path: Path) -> None:
    directory = copy_dir(tmp_path)
    data = json.loads((directory / "ncm.json").read_text(encoding="utf-8"))
    data["entries"][0][1] = "Descrição adulterada"
    (directory / "ncm.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(OfficialTablesError, match="SHA-256"):
        load_official_catalog(directory)


def test_missing_file_and_bad_manifest_are_refused(tmp_path: Path) -> None:
    directory = copy_dir(tmp_path)
    (directory / "cclasstrib.json").unlink()
    with pytest.raises(OfficialTablesError, match="unreadable"):
        load_official_catalog(directory)
    broken = copy_dir(tmp_path / "b")
    manifest = json.loads((broken / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema"] = "other/v9"
    (broken / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OfficialTablesError, match="schema"):
        load_official_catalog(broken)


def official_service(build_service, catalog):  # type: ignore[no-untyped-def]
    return build_service(None, baselines=default_baselines(classification_catalog=catalog))


def test_classification_verifies_ncm_and_cclasstrib_against_official_tables(  # type: ignore[no-untyped-def]
    build_service, catalog
) -> None:
    ok = official_service(build_service, catalog).advise(
        cls_request(ncm="84713012", cclasstrib="000001")
    )
    text = texts(ok)
    assert "tabela oficial não carregada" not in text
    assert "catálogo oficial não carregado" not in text
    assert "não consta" not in text
    assert "integridade verificada" in text
    bad = official_service(build_service, catalog).advise(
        cls_request(ncm="99999999", cclasstrib="999999")
    )
    assert "NCM 99999999 não consta da tabela carregada" in texts(bad)
    assert "cClassTrib 999999 não consta do catálogo carregado" in texts(bad)


def test_default_baselines_still_report_not_verified_without_official_tables(  # type: ignore[no-untyped-def]
    build_service,
) -> None:
    result = build_service(None, baselines=default_baselines()).advise(
        cls_request(cclasstrib="000001")
    )
    assert "catálogo oficial não carregado" in texts(result)


def test_composition_falls_back_to_seed_when_official_tables_fail(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom() -> None:
        raise OfficialTablesError("corrupt")

    monkeypatch.setattr(composition, "cached_official_catalog", boom)

    class Reader:
        def surface(self, **kwargs):  # type: ignore[no-untyped-def]
            return ()

    identity = object.__new__(HumanIdentityService)
    router = composition.build_cognitive_router(
        identity, Reader(), {"NFCORE_COGNITIVE_ENABLED": "true"}  # type: ignore[arg-type]
    )
    assert router is not None
