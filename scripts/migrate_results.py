"""Migrate legacy result JSON files to the unified schema.

Legacy formats handled
----------------------
1. Hardware (tau-sweep): top-level `job_id`, `backend`, `shots`, `protocol`
   with `tau_values`, `theta_samples`, and a `results` dict keyed by
   ``theta_<i>_tau_<t>``.
2. Simulation (noise-sweep): top-level `protocol` with `p_list`, top-level
   `fidelities` array, and `metadata` carrying `mode` ("exact" /
   "sampled (...)").

For each input file the original is moved to ``results/legacy/`` and the
unified version is written to ``results/<original_name>``.

Run with:  python scripts/migrate_results.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

RESULTS_DIR = Path("results")
LEGACY_DIR = RESULTS_DIR / "legacy"
DEFAULT_OPT_LEVEL = 3


def _is_hardware(raw: dict[str, Any]) -> bool:
    return "results" in raw and "job_id" in raw


def _is_simulation(raw: dict[str, Any]) -> bool:
    return "fidelities" in raw and "results" not in raw


def _convert_hardware(raw: dict[str, Any]) -> dict[str, Any]:
    proto = raw["protocol"]
    M = int(proto["M"])
    N = int(proto["N"])
    nt = int(proto.get("nt", 1))
    theta_samples = proto.get("theta_samples")
    if theta_samples is None:
        theta_samples = [proto.get("thetas", [])]
    tau_values = sorted({int(t) for t in proto.get("tau_values", [])})

    # Build (nt, n_tau) -> entry lookup
    entries = raw["results"]
    fid_grid = np.full((nt, len(tau_values), N), np.nan)
    counts_grid: list[list[dict | None]] = [
        [None for _ in tau_values] for _ in range(nt)
    ]

    tau_index = {tau: j for j, tau in enumerate(tau_values)}
    for entry in entries.values():
        ti = int(entry.get("theta_idx", 0))
        tau = int(entry["tau"])
        j = tau_index[tau]
        fid_grid[ti, j, :] = entry["fidelities"]
        counts_grid[ti][j] = entry["counts"]

    avg_fids = np.nanmean(fid_grid, axis=0).tolist()  # (n_tau, N)

    optimization_level = int(raw.get("optimization_level", DEFAULT_OPT_LEVEL))

    return {
        "timestamp": raw.get("timestamp", ""),
        "experiment_type": "hardware",
        "backend": raw.get("backend", "unknown"),
        "optimization_level": optimization_level,
        "job_id": raw.get("job_id"),
        "shots": raw.get("shots"),
        "seed": raw.get("seed"),
        "n_samples": None,
        "protocol": {
            "M": M,
            "N": N,
            "alpha": proto.get("alpha"),
            "use_qec": bool(proto.get("use_qec", False)),
            "theta_samples": theta_samples,
        },
        "sweep": {"axis": "tau", "values": tau_values},
        "fidelities": avg_fids,
        "per_theta_fidelities": fid_grid.tolist() if nt > 1 else None,
        "counts": counts_grid,
        "metadata": {},
    }


def _convert_simulation(raw: dict[str, Any]) -> dict[str, Any]:
    proto = raw["protocol"]
    meta = dict(raw.get("metadata", {}))

    M = int(proto["M"])
    N = int(proto["N"])
    p_list = list(proto.get("p_list", []))
    thetas = proto.get("thetas", [])
    n_samples = proto.get("n_samples") or meta.get("n_samples")

    raw_mode = str(meta.get("mode", "")).lower()
    if "sampl" in raw_mode or n_samples:
        backend_label = "aer_sampling"
    else:
        backend_label = "aer_exact"
        n_samples = None

    # Strip duplicates already represented at top level
    for k in (
        "mode",
        "M",
        "N",
        "use_qec",
        "thetas",
        "p_list",
        "alpha",
        "n_samples",
        "timestamp",
    ):
        meta.pop(k, None)

    return {
        "timestamp": raw.get("timestamp", ""),
        "experiment_type": "simulation",
        "backend": backend_label,
        "optimization_level": None,
        "job_id": None,
        "shots": None,
        "seed": proto.get("seed"),
        "n_samples": n_samples,
        "protocol": {
            "M": M,
            "N": N,
            "alpha": proto.get("alpha"),
            "use_qec": bool(proto.get("use_qec", False)),
            "theta_samples": [thetas],
        },
        "sweep": {"axis": "p", "values": p_list},
        "fidelities": raw["fidelities"],
        "per_theta_fidelities": None,
        "counts": None,
        "metadata": meta,
    }


def convert(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a legacy raw dict to the unified schema. Returns None if
    the file already looks unified or the format is unrecognized."""
    if "experiment_type" in raw and "sweep" in raw:
        return None  # already unified
    if _is_hardware(raw):
        return _convert_hardware(raw)
    if _is_simulation(raw):
        return _convert_simulation(raw)
    return None


def main() -> None:
    files = sorted(RESULTS_DIR.glob("run_*.json"))
    if not files:
        print(f"No run_*.json files in {RESULTS_DIR}/")
        return

    LEGACY_DIR.mkdir(parents=True, exist_ok=True)

    converted = 0
    skipped = 0
    for fp in files:
        with open(fp) as f:
            raw = json.load(f)
        unified = convert(raw)
        if unified is None:
            print(f"  skip   {fp.name} (already unified or unknown format)")
            skipped += 1
            continue

        # Backup original, then overwrite.
        shutil.move(str(fp), str(LEGACY_DIR / fp.name))
        with open(fp, "w") as f:
            json.dump(unified, f, indent=2)
        print(
            f"  ok     {fp.name}  [{unified['experiment_type']}, "
            f"backend={unified['backend']}, opt={unified['optimization_level']}]"
        )
        converted += 1

    print(f"\nDone. converted={converted}, skipped={skipped}, "
          f"originals backed up to {LEGACY_DIR}/")


if __name__ == "__main__":
    main()
