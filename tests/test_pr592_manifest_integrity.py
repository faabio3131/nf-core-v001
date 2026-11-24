"""NF592-07: the historical manifest must cover every task/path reference."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs" / "audit"


def test_reconciliation_manifest_covers_all_file_extensions():
    source = AUDIT / "NFCORE_CURRENT_RECONCILIATION_59_TASKS_42_MUNICIPALITIES_2026-11-19.md"
    manifest = AUDIT / "NFCORE_7PRS_ZERO_LOSS_149_PATHS_20261123.json"
    entries = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| NFV1-"):
            continue
        task = line.split("|")[1].strip()
        for path in re.findall(r"`([^`]+)`", line):
            if re.match(r"^(src|tests|docs|scripts|deploy|\.github|portal)/", path):
                entries.append({"task": task, "path": path})
    record = json.loads(manifest.read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in entries}
    assert entries == record["task_references"]
    assert len(entries) == record["references_total"] == 151
    assert len(paths) == record["unique_paths_count"] == 114
    assert paths == {entry["path"] for entry in record["paths"]}
    assert {"portal/index.html", "portal/styles.css"} <= paths
    assert all((ROOT / path).is_file() for path in paths)
