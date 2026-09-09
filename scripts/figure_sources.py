"""Pinned manuscript inputs and explicitly documented historical overlays."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from broadcasting.results import load_run

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "figures" / "sources.json"


def source_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def load_source(relative_path: str, *, manifest: dict | None = None) -> dict:
    """Read a verified source, filling only explicitly documented missing fields."""
    manifest = source_manifest() if manifest is None else manifest
    spec = manifest["runs"][relative_path]
    path = ROOT / relative_path
    if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
        raise ValueError(f"Figure source changed: {relative_path}; review and update the manifest explicitly.")
    if relative_path.startswith("results/qec513/"):
        run = json.loads(path.read_text())
        run.update(filename=path.name, filepath=str(path))
    else:
        run = load_run(path)
    for field, override in spec.get("historical_overrides", {}).items():
        if not override.get("evidence"):
            raise ValueError(f"Historical {field} override has no source evidence: {relative_path}")
        if field == "dt":
            run["metadata"] = run.get("metadata") or {}
            target = run["metadata"]
        else:
            target = run
        if target.get(field) is None:
            target[field] = override["value"]
        elif target[field] != override["value"]:
            raise ValueError(f"Historical override conflicts with recorded {field}: {relative_path}")
    run["historical_provenance"] = spec.get("historical_overrides", {})
    return run


def figure_runs(key: str) -> list[dict]:
    manifest = source_manifest()
    return [load_source(path, manifest=manifest) for path in manifest["figures"][key]["sources"]]
