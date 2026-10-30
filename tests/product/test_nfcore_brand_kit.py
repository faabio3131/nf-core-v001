import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "docs" / "brand"
PORTAL = ROOT / "portal"


def test_nfcore_brand_kit_is_canonical_and_machine_readable() -> None:
    guide = (BRAND / "FM_NFCORE_V1_BRAND_KIT.md").read_text(encoding="utf-8")
    tokens = json.loads((BRAND / "fm-nfcore.tokens.json").read_text(encoding="utf-8"))

    assert "FM NFCORE" in guide
    assert "Infraestrutura fiscal. Sob controle." in guide
    assert "Infrastructure Mission Control" in guide
    assert tokens["meta"]["product"] == "FM NFCORE"
    assert tokens["meta"]["tagline"] == "Infraestrutura fiscal. Sob controle."
    assert tokens["color"]["brand"]["obsidian"]["$value"] == "#08121F"
    assert tokens["color"]["brand"]["electricBlue"]["$value"] == "#2563FF"
    assert tokens["color"]["brand"]["polarCyan"]["$value"] == "#00E5FF"
    assert tokens["color"]["status"]["success"]["$value"] == "#22C55E"
    assert tokens["color"]["status"]["success"]["$value"] not in {
        tokens["color"]["brand"]["electricBlue"]["$value"],
        tokens["color"]["brand"]["polarCyan"]["$value"],
    }


def test_nfcore_vector_assets_are_present_and_accessible() -> None:
    mark = (PORTAL / "assets" / "fm-nfcore-mark.svg").read_text(encoding="utf-8")
    favicon = (PORTAL / "assets" / "favicon.svg").read_text(encoding="utf-8")

    assert "<title" in mark
    assert "FM NFCORE" in mark
    assert "#2563ff" in mark.lower()
    assert "#00e5ff" in mark.lower()
    assert 'aria-label="FM NFCORE"' in favicon


def test_brand_kit_preserves_fiscal_safety_language() -> None:
    guide = (BRAND / "FM_NFCORE_V1_BRAND_KIT.md").read_text(encoding="utf-8")
    app = (PORTAL / "app.js").read_text(encoding="utf-8")

    for guard in ("PROD BLOQUEADA", "BLOCKED_EXTERNAL", "HUMAN_APPROVAL_REQUIRED"):
        assert guard in guide
        assert guard in app


def test_portal_uses_provider_neutral_commercial_channel_language() -> None:
    app = (PORTAL / "app.js").read_text(encoding="utf-8")

    assert "Canais de venda e pagamento" in app
    assert "Canais de venda governados por adaptadores" in app
    assert "Adaptador ativo: Cakto." in app
    assert '["checkout-admin", "Checkout Cakto"]' not in app


def test_portal_brand_shell_preserves_accessibility_and_responsive_contract() -> None:
    index = (PORTAL / "index.html").read_text(encoding="utf-8")
    styles = (PORTAL / "styles.css").read_text(encoding="utf-8")

    assert 'class="skip-link"' in index
    assert 'lang="pt-BR"' in index
    assert "assets/favicon.svg" in index
    assert "assets/nfcore-emblem-approved.png" in index
    assert 'src="assets/nfcore-logo-core-only.png"' in index
    assert (PORTAL / "assets" / "nfcore-logo-core-only.png").is_file()
    assert (PORTAL / "assets" / "nfcore-logo-approved.png").is_file()
    assert "assets/fm-nfcore-mark.svg" not in index
    for breakpoint in ("1050px", "760px", "480px"):
        assert breakpoint in styles
    assert "prefers-reduced-motion: reduce" in styles
