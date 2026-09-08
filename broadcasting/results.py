"""JSON I/O for broadcasting experiment results.

All files use a single unified schema regardless of whether they come
from exact / sampling simulations or real hardware runs.  ``load_run``
also populates a few legacy keys (``entries``, ``nt`` …) so older
plotting helpers keep working unchanged.
"""

from __future__ import annotations

import json
import os
import uuid
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .protocol import BroadcastResult, ProtocolConfig

RESULTS_DIR = Path("results")
DEFAULT_OPTIMIZATION_LEVEL = 3


def _default_run_suffix() -> str:
    """SLURM identity, when available, plus randomness unique to every save."""
    job_id = os.environ.get("SLURM_JOB_ID")
    task_id = os.environ.get("SLURM_ARRAY_TASK_ID")
    label = f"_{job_id}" if job_id else ""
    if job_id and task_id is not None:
        label += f"_{task_id}"
    return f"{label}_{uuid.uuid4().hex}"


def write_run_json(data: dict[str, Any], filepath: str | Path) -> Path:
    """Publish complete JSON atomically, refusing to overwrite any existing path.

    The temporary file and destination live on the same filesystem. Hard-link
    creation is atomic and exclusive, so readers never see a partial record.
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=filepath.parent, prefix=".run_",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, indent=2, default=_json_default, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, filepath)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return filepath


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_run(
    result: BroadcastResult,
    config: ProtocolConfig,
    filepath: str | Path | None = None,
    results_dir: str | Path = RESULTS_DIR,
    *,
    optimization_level: int | None = None,
) -> Path:
    """Serialize a run to a timestamped JSON file using the unified schema.

    The shape of ``result.fidelities`` is interpreted from the backend
    mode recorded in ``result.metadata["mode"]``:

    - ``exact`` / ``sampled (...)``  -> simulation, p sweep
    - ``hardware (...)``              -> hardware, single fidelity point
      (tau-sweep hardware runs typically save the JSON directly from
      the submission notebook, not through this helper).
    """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = results_dir / f"run_{timestamp}{_default_run_suffix()}.json"
    else:
        filepath = Path(filepath)

    meta = dict(result.metadata)
    mode = str(meta.get("mode", "")).lower()

    if mode.startswith("hardware"):
        experiment_type = "hardware"
        backend_label = meta.get("backend", "unknown")
        opt_level = (
            optimization_level
            if optimization_level is not None
            else int(meta.get("optimization_level", DEFAULT_OPTIMIZATION_LEVEL))
        )
        sweep_axis = meta.get("sweep_axis", "tau")
        sweep_values = meta.get("sweep_values")
        if sweep_values is None:
            sweep_values = [meta.get("tau")] if meta.get("tau") is not None else [0]
            fidelities = [list(result.fidelities)]
            counts_field = [[meta["counts"]]] if "counts" in meta else None
        else:
            sweep_values = list(sweep_values)
            fidelities = result.fidelities
            counts_field = meta.get("counts")
        n_samples = None
        theta_samples = meta.get("theta_samples", [list(meta.get("thetas", config.thetas))])
    elif mode.startswith("hpc"):
        # A submission receipt (command built/submitted, no results yet) --
        # not a completed sweep, so no sweep values/fidelities are recorded.
        # Reconstruct the requested run from `metadata.command`.
        experiment_type = "hpc_submission"
        backend_label = "hpc"
        opt_level = None
        sweep_axis = "p"
        sweep_values = []
        fidelities = []
        counts_field = None
        n_samples = None
        theta_samples = [list(meta.get("thetas", config.thetas))]
    else:
        experiment_type = "simulation"
        if "sampl" in mode:
            backend_label = "aer_sampling"
            n_samples = meta.get("n_samples", config.n_samples)
        else:
            backend_label = "aer_exact"
            n_samples = None
        opt_level = None
        sweep_axis = "p"
        sweep_values = list(meta.get("p_list", config.p_list))
        fidelities = result.fidelities
        counts_field = None
        theta_samples = [list(meta.get("thetas", config.thetas))]

    extra_meta = {
        k: v
        for k, v in meta.items()
        if k
        not in {
            "mode",
            "M",
            "N",
            "use_qec",
            "thetas",
            "p_list",
            "alpha",
            "n_samples",
            "seed",
            "tau",
            "shots",
            "backend",
            "job_id",
            "counts",
            "optimization_level",
            "theta_samples",
            "sweep_axis",
            "sweep_values",
            "per_theta_fidelities",
            "timestamp",
        }
        and _is_json_serializable(v)
    }

    data: dict[str, Any] = {
        "timestamp": meta.get("timestamp", datetime.now().isoformat()),
        "experiment_type": experiment_type,
        "backend": backend_label,
        "optimization_level": opt_level,
        "job_id": meta.get("job_id"),
        "shots": meta.get("shots"),
        "seed": meta.get("seed", config.seed),
        "n_samples": n_samples,
        "protocol": {
            "M": meta.get("M", config.M),
            "N": meta.get("N", config.N),
            "alpha": meta.get("alpha", config.alpha),
            "use_qec": meta.get("use_qec", config.use_qec),
            "theta_samples": theta_samples,
            "linear_feedforward": meta.get("linear_feedforward", config.linear_feedforward),
            "outcomes_list": meta.get("outcomes_list", config.outcomes_list),
        },
        "sweep": {"axis": sweep_axis, "values": sweep_values},
        "fidelities": fidelities,
        "per_theta_fidelities": meta.get("per_theta_fidelities"),
        "counts": counts_field,
        "metadata": extra_meta,
    }

    return write_run_json(data, filepath)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_run(filepath: str | Path) -> dict[str, Any]:
    """Load a unified-schema run JSON file.

    Returns a dict with all unified fields plus legacy aliases
    (``entries``, ``nt``, ``tau_values`` …) used by older plotting code.
    """
    with open(filepath) as f:
        raw = json.load(f)

    if "experiment_type" not in raw or "sweep" not in raw:
        raise ValueError(
            f"{filepath} is not in the unified schema. "
            "Run scripts/migrate_results.py to convert legacy files."
        )

    proto = raw["protocol"]
    sweep = raw["sweep"]
    theta_samples = proto.get("theta_samples", [[]])
    nt = len(theta_samples)
    fidelities = raw["fidelities"]

    # Legacy `entries` view (one record per sweep point per theta sample).
    entries: list[dict[str, Any]] = []
    per_theta = raw.get("per_theta_fidelities")
    counts_grid = raw.get("counts")
    sweep_values = sweep.get("values", [])
    sweep_key = "tau" if sweep["axis"] == "tau" else "p"
    for ti, thetas in enumerate(theta_samples):
        for j, sv in enumerate(sweep_values):
            if per_theta is not None:
                fids_ij = per_theta[ti][j]
            elif ti == 0:
                fids_ij = fidelities[j]
            else:
                continue
            entry: dict[str, Any] = {
                "theta_idx": ti,
                "thetas": thetas,
                sweep_key: sv,
                "fidelities": fids_ij,
            }
            if counts_grid is not None:
                entry["counts"] = counts_grid[ti][j]
            entries.append(entry)

    return {
        # Unified schema fields
        "filepath": str(filepath),
        "filename": Path(filepath).name,
        "timestamp": raw.get("timestamp", ""),
        "experiment_type": raw["experiment_type"],
        "backend": raw.get("backend"),
        "optimization_level": raw.get("optimization_level"),
        "job_id": raw.get("job_id"),
        "shots": raw.get("shots"),
        "seed": raw.get("seed"),
        "n_samples": raw.get("n_samples"),
        "sweep": sweep,
        "fidelities": fidelities,
        "per_theta_fidelities": per_theta,
        "counts": counts_grid,
        "metadata": raw.get("metadata", {}),
        # Convenience / legacy aliases
        "protocol": proto,
        "linear_feedforward": proto.get("linear_feedforward"),
        "outcomes_list": proto.get("outcomes_list"),
        "M": proto["M"],
        "N": proto["N"],
        "alpha": proto.get("alpha"),
        "use_qec": proto.get("use_qec", False),
        "nt": nt,
        "theta_samples": theta_samples,
        "tau_values": sweep["values"] if sweep["axis"] == "tau" else [],
        "p_list": sweep["values"] if sweep["axis"] == "p" else [],
        "entries": entries,
    }


def list_runs(results_dir: str | Path = RESULTS_DIR) -> list[dict[str, Any]]:
    """List all run files under *results_dir*, skipping unreadable ones."""
    results_dir = Path(results_dir)
    runs = []
    for f in sorted(results_dir.glob("run_*.json")):
        try:
            runs.append(load_run(f))
        except Exception as e:
            print(f"Skipping {f.name}: {e}")
    return runs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_json_serializable(v: Any) -> bool:
    try:
        json.dumps(v, default=_json_default)
        return True
    except (TypeError, ValueError):
        return False


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
