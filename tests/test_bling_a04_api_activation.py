"""Production Bling API activation: opt-in, canonical API, safe mounts."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ibling_api_overlay_only_extends_existing_api() -> None:
    overlay = yaml.safe_load(
        (ROOT / "deploy/contabo/compose.bling.api.opt-in.yml").read_text()
    )
    assert list(overlay["services"]) == ["nfcore-api"]
    api = overlay["services"]["nfcore-api"]
    assert api["environment"]["NFCORE_BLING_INSTALLATIONS_ENABLED"] == "true"
    assert api["environment"]["NFCORE_BLING_CLIENT_SECRET_FILE"] == (
        "/run/nfcore/bling/client-secret"
    )
    assert api["environment"]["NFCORE_BLING_TOKEN_MASTER_KEY_FILE"] == (
        "/run/nfcore/bling/master-key"
    )
    assert api["volumes"][0]["type"] == "bind"
    assert api["volumes"][0]["read_only"] is True
    assert api["volumes"][0]["bind"]["create_host_path"] is False
    assert api["volumes"][0]["target"] == "/run/nfcore/bling"
    assert api["env_file"][1]["required"] is True


def test_bling_api_activated_only_by_host_owned_opt_in() -> None:
    base = yaml.safe_load((ROOT / "deploy/contabo/compose.prod.yml").read_text())
    api = base["services"]["nfcore-api"]
    # Production already has exactly one canonical encrypted A1 Vault bind.
    # Bling opt-in must not be enabled merely because the A1 bind exists.
    volumes = api.get("volumes", [])
    assert len(volumes) == 1
    vault = volumes[0]
    assert vault["type"] == "bind"
    assert vault["source"] == "/var/lib/nfcore/vault"
    assert vault["target"] == "/var/lib/nfcore/vault"
    assert vault["read_only"] is False
    assert vault["bind"]["create_host_path"] is False
    assert api["environment"].get("NFCORE_BLING_INSTALLATIONS_ENABLED") != "true"
    assert "nfcore-bling-worker" not in base["services"]
    deploy = (ROOT / "deploy/contabo/deploy.sh").read_text()
    assert "compose.bling.api.opt-in.yml" not in deploy
    assert "NFCORE_SCHEMA_MIGRATION_APPROVED=true" not in deploy


def test_no_bling_credentials_committed_in_activation_template() -> None:
    text = (ROOT / "deploy/contabo/.env.bling.api.example").read_text()
    assert "NFCORE_BLING_CLIENT_ID=\n" in text
    assert "NFCORE_BLING_APPROVED_SCOPES=\n" in text
    assert "NFCORE_BLING_CLIENT_SECRET=" not in text
    assert "NFCORE_BLING_COMPANY_ID=" not in text
