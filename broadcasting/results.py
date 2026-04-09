"""JSON I/O for broadcasting experiment results."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .protocol import BroadcastResult, ProtocolConfig

RESULTS_DIR = Path("results")


def save_run(
    result: BroadcastResult,
    config: ProtocolConfig,
    filepath: str | Path | None = None,
    results_dir: str | Path = RESULTS_DIR,
) -> Path:
    """Serialize a run to a timestamped JSON file.

    Parameters
    ----------
    result : BroadcastResult
        Run output.
    config : ProtocolConfig
        Protocol parameters used.
    filepath : Path or None
        Explicit output path.  If None, a timestamped name is generated
        inside *results_dir*.
    results_dir : Path
        Directory for auto-generated filenames.

    Returns
    -------
    Path
        Written file path.
    """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = results_dir / f"run_{timestamp}.json"
    else:
        filepath = Path(filepath)

    data: dict[str, Any] = {
        "timestamp": result.metadata.get("timestamp", datetime.now().isoformat()),
        "protocol": {
            "M": config.M,
            "N": config.N,
            "alpha": config.alpha,
            "thetas": config.thetas,
            "p_list": config.p_list,
            "use_qec": config.use_qec,
            "n_samples": config.n_samples,
            "seed": config.seed,
        },
        "fidelities": result.fidelities,
        "metadata": {
            k: v
            for k, v in result.metadata.items()
            if _is_json_serializable(v)
        },
    }

    # Include hardware-specific fields when present
    for key in ("backend", "job_id", "shots", "counts", "tau"):
        if key in result.metadata:
            data[key] = result.metadata[key]

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=_json_default)

    return filepath


def load_run(filepath: str | Path) -> dict[str, Any]:
    """Load a run JSON file and normalize old / new formats.

    Parameters
    ----------
    filepath : str or Path
        Path to the JSON file.

    Returns
    -------
    dict
        Normalized run data with keys: ``filepath``, ``filename``,
        ``timestamp``, ``job_id``, ``backend``, ``shots``, ``M``, ``N``,
        ``use_qec``, ``nt``, ``theta_samples``, ``tau_values``,
        ``entries``, ``fidelities``, ``metadata``.
    """
    with open(filepath) as f:
        raw = json.load(f)

    # New format (from save_run)
    if "fidelities" in raw and "results" not in raw:
        return {
            "filepath": str(filepath),
            "filename": Path(filepath).name,
            "timestamp": raw.get("timestamp", ""),
            "job_id": raw.get("job_id", ""),
            "backend": raw.get("backend", raw.get("metadata", {}).get("mode", "simulation")),
            "shots": raw.get("shots", 0),
            "M": raw["protocol"]["M"],
            "N": raw["protocol"]["N"],
            "use_qec": raw["protocol"].get("use_qec", False),
            "nt": 1,
            "theta_samples": [raw["protocol"].get("thetas", [])],
            "tau_values": [],
            "entries": [],
            "fidelities": raw["fidelities"],
            "metadata": raw.get("metadata", {}),
        }

    # Legacy hardware format
    proto = raw["protocol"]
    M, N = proto["M"], proto["N"]
    use_qec = proto.get("use_qec", None)
    shots = raw["shots"]
    tau_values = proto.get("tau_values", raw.get("tau_values", []))

    entries = []
    for key, entry in raw["results"].items():
        if "theta_idx" in entry:
            entries.append({
                "theta_idx": entry["theta_idx"],
                "thetas": entry["thetas"],
                "tau": entry["tau"],
                "fidelities": entry["fidelities"],
                "counts": entry["counts"],
            })
        else:
            entries.append({
                "theta_idx": 0,
                "thetas": proto.get("thetas", []),
                "tau": int(key),
                "fidelities": entry["fidelities"],
                "counts": entry["counts"],
            })

    return {
        "filepath": str(filepath),
        "filename": Path(filepath).name,
        "timestamp": raw.get("timestamp", ""),
        "job_id": raw.get("job_id", ""),
        "backend": raw.get("backend", "unknown"),
        "shots": shots,
        "seed": raw.get("seed", None),
        "M": M,
        "N": N,
        "use_qec": use_qec,
        "nt": proto.get("nt", 1),
        "theta_samples": proto.get("theta_samples", [proto.get("thetas", [])]),
        "tau_values": sorted(set(tau_values)),
        "entries": entries,
    }


def list_runs(results_dir: str | Path = RESULTS_DIR) -> list[dict[str, Any]]:
    """List all run files with summary info.

    Parameters
    ----------
    results_dir : str or Path
        Directory to scan.

    Returns
    -------
    list[dict]
        Loaded and normalized run records, sorted by filename.
    """
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
