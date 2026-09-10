"""One measured-result schema and store for broadcasting and quantum memory.

Records retain per-preparation counts, receiver fidelities, execution details,
and source evidence. Plotting and analysis both read them through ``load_run``.
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

SCHEMA_VERSION = 2
RESULTS_DIR = Path("results")
DEFAULT_OPTIMIZATION_LEVEL = 3
_EXECUTION_DOCUMENT_TYPES = {"execution", "hpc_execution"}


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

def make_run_record(
    result: BroadcastResult,
    config: ProtocolConfig,
    *,
    metadata: dict[str, Any] | None = None,
    optimization_level: int | None = None,
) -> dict[str, Any]:
    """Build a self-contained broadcasting record without writing any files.

    The shape of ``result.fidelities`` is interpreted from the backend
    mode recorded in ``result.metadata["mode"]``:

    - ``exact`` / ``sampled (...)``  -> simulation, p sweep
    - ``hardware (...)``              -> hardware, single point or delay sweep
    - ``hpc (...)``                   -> submission receipt, without measurements

    Executed metadata takes precedence over configuration defaults. Existing
    settings are preserved in the returned JSON-compatible dictionary.
    """
    meta = dict(result.metadata)
    meta.update(metadata or {})
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

    data.update(schema_version=SCHEMA_VERSION, experiment_kind="broadcasting",
                record_id=uuid.uuid4().hex)
    data["sweep"]["unit"] = "dt" if sweep_axis == "tau" else "probability"
    data["config"] = configuration_from_record(data)
    data = json.loads(json.dumps(data, default=_json_default, allow_nan=False))
    validate_run_record(data)
    return data


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def make_memory_record(
    result: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a measured one-qubit memory record without writing any files.

    ``result`` provides ``state_prep`` (theta and phi), ``use_qec``,
    ``tau_values``, ``backend_fidelities`` and optional ``backend_counts``.
    ``ideal_fidelities`` is an optional numerical reference on the same grid.
    Hardware and local simulations use this same interface. An explicit
    encoding flag is required; circuit type is never inferred from a filename.
    """
    preparation = dict(result.get("state_prep", {}))
    if not {"theta", "phi"} <= preparation.keys():
        raise ValueError("Memory results require state_prep theta and phi")
    use_qec = result.get("use_qec", (result.get("protocol") or {}).get("use_qec"))
    if not isinstance(use_qec, (bool, np.bool_)):
        raise ValueError("Memory results require an explicit boolean use_qec")
    sweep_values = list(result["tau_values"])
    values = result.get("backend_fidelities", result.get("fidelities"))
    if values is None:
        raise ValueError("Memory results require measured fidelities")
    fidelities = np.asarray(values, dtype=float).reshape(len(sweep_values), 1).tolist()
    count_values = result.get("backend_counts", result.get("counts"))
    counts = None if count_values is None else [list(count_values)]
    record_metadata = dict(result.get("metadata") or {})
    record_metadata.update(metadata or {})
    backend = result.get("backend")
    data = {
        "schema_version": SCHEMA_VERSION,
        "record_id": uuid.uuid4().hex,
        "experiment_kind": "memory",
        "timestamp": result.get("timestamp", datetime.now().isoformat()),
        "experiment_type": result.get("experiment_type", "hardware"),
        "backend": backend,
        "optimization_level": result.get("optimization_level"),
        "job_id": result.get("job_id"),
        "shots": result.get("shots"),
        "seed": result.get("seed"),
        "n_samples": None,
        "protocol": {
            "M": 0, "N": 1, "alpha": None, "use_qec": bool(use_qec),
            "theta_samples": [[preparation["theta"], preparation["phi"]]],
            "state_prep": preparation,
            "linear_feedforward": None, "outcomes_list": None,
        },
        "sweep": {"axis": "tau", "unit": "dt", "values": sweep_values},
        "fidelities": fidelities,
        "per_theta_fidelities": None,
        "counts": counts,
        "metadata": record_metadata,
    }
    if result.get("ideal_fidelities") is not None:
        reference = np.asarray(result["ideal_fidelities"], dtype=float)
        data["reference_fidelities"] = {"ideal": reference.reshape(len(sweep_values), 1).tolist()}
    data["config"] = configuration_from_record(data)
    data = json.loads(json.dumps(data, default=_json_default, allow_nan=False))
    validate_run_record(data)
    return data


def save_run(result: BroadcastResult, config: ProtocolConfig,
             filepath: str | Path | None = None, results_dir: str | Path = RESULTS_DIR,
             *, optimization_level: int | None = None,
             metadata: dict[str, Any] | None = None) -> Path:
    """Save a self-contained broadcasting record, refusing existing destinations."""
    data = make_run_record(result, config, metadata=metadata,
                           optimization_level=optimization_level)
    destination = filepath if filepath is not None else Path(results_dir) / f"run{_default_run_suffix()}.json"
    return write_run_json(data, destination)


def save_memory_run(result: dict[str, Any], filepath: str | Path | None = None,
                    results_dir: str | Path = RESULTS_DIR,
                    *, metadata: dict[str, Any] | None = None) -> Path:
    """Save a self-contained memory record, refusing existing destinations."""
    data = make_memory_record(result, metadata=metadata)
    destination = filepath if filepath is not None else Path(results_dir) / f"run_{data['record_id']}.json"
    return write_run_json(data, destination)


def configuration_from_record(data: dict[str, Any]) -> dict[str, Any]:
    """Expose all recorded executed settings without inventing missing metadata."""
    return {"experiment_kind": data["experiment_kind"],
            "experiment_type": data["experiment_type"], "backend": data.get("backend"),
            "protocol": data["protocol"], "sweep": data["sweep"],
            "shots": data.get("shots"), "seed": data.get("seed"),
            "n_samples": data.get("n_samples"),
            "optimization_level": data.get("optimization_level")}


def validate_run_record(data: dict[str, Any]) -> None:
    """Validate record structure without estimating or changing any quantity."""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Expected measured-result schema_version={SCHEMA_VERSION}")
    if data.get("experiment_kind") == "convergence_summary":
        _validate_summary(data)
        return
    if data.get("experiment_kind") not in {"broadcasting", "memory"}:
        raise ValueError("experiment_kind must be broadcasting or memory")
    if data.get("experiment_type") not in {"hardware", "simulation", "hpc_submission"}:
        raise ValueError("Unknown experiment_type")
    if not isinstance(data.get("record_id"), str) or not data["record_id"]:
        raise ValueError("A nonempty record_id is required")
    protocol = data["protocol"]
    receivers = protocol["N"]
    if not isinstance(receivers, int) or receivers < 1:
        raise ValueError("protocol.N must be a positive integer")
    if data["experiment_kind"] == "memory" and (protocol["M"] != 0 or receivers != 1):
        raise ValueError("Memory records have zero senders and one receiver")
    samples = protocol.get("theta_samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("theta_samples must retain at least one preparation")
    sweep = data["sweep"]
    values = np.asarray(sweep["values"], dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("sweep.values must be a finite one-dimensional grid")
    size = len(values)

    def check_fidelities(value: Any, shape: tuple[int, ...], field: str) -> None:
        array = np.asarray(value, dtype=float)
        if not size and array.size == 0:
            return
        if array.shape != shape:
            raise ValueError(f"{field} shape {array.shape} does not match {shape}")
        if not np.isfinite(array).all() or np.any(array < -1e-12) or np.any(array > 1 + 1e-12):
            raise ValueError(f"{field} must contain finite fidelities in [0, 1]")

    check_fidelities(data["fidelities"], (size, receivers), "fidelities")
    per_theta = data.get("per_theta_fidelities")
    if per_theta is not None:
        check_fidelities(per_theta, (len(samples), size, receivers), "per_theta_fidelities")
    for name, reference in (data.get("reference_fidelities") or {}).items():
        check_fidelities(reference, (size, receivers), f"reference_fidelities.{name}")
    counts = data.get("counts")
    if counts is not None:
        if len(counts) != len(samples) or any(len(row) != size for row in counts):
            raise ValueError("counts must have shape [preparation][sweep]")
        for row in counts:
            for histogram in row:
                if not isinstance(histogram, dict):
                    raise ValueError("Each count histogram must be a dictionary")
                if any(not isinstance(key, str) or len(key) != receivers or set(key) - {"0", "1"}
                       for key in histogram):
                    raise ValueError("Count keys must be receiver-register bitstrings")
                if any(not isinstance(count, (int, np.integer)) or isinstance(count, bool) or count < 0
                       for count in histogram.values()):
                    raise ValueError("Counts must be nonnegative integers")
                if data.get("shots") is not None and sum(histogram.values()) != data["shots"]:
                    raise ValueError("Histogram shot total disagrees with recorded shots")
    if "campaign" in (data.get("metadata") or {}):
        raise ValueError("Result collection identity belongs in metadata.execution")


def _validate_summary(data: dict[str, Any]) -> None:
    if not isinstance(data.get("record_id"), str) or not data["record_id"]:
        raise ValueError("A nonempty record_id is required")
    if data.get("fidelities") is not None or data.get("counts") is not None:
        raise ValueError("A convergence summary cannot claim unavailable raw measurements")
    counts = data.get("sample_counts", [])
    errors = np.asarray(data.get("errors_per_receiver"), dtype=float)
    receivers = data.get("config", {}).get("N")
    if (not counts or errors.shape != (len(counts), receivers)
            or not np.isfinite(errors).all() or (errors < 0).any()):
        raise ValueError("Convergence summary needs finite errors for every sample count and receiver")
    if data.get("raw_fidelity_grids_available") is not False:
        raise ValueError("Convergence summary must explicitly identify unavailable raw grids")


def _read_document(filepath: str | Path) -> dict[str, Any]:
    with open(filepath, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Result must be a JSON object: {filepath}")
    return raw


def _measurements(document: dict[str, Any]) -> list[dict[str, Any]]:
    kind = document.get("document_type")
    if kind in _EXECUTION_DOCUMENT_TYPES:
        if document.get("schema_version") != 3:
            raise ValueError("Expected execution schema_version=3")
        records = document.get("measurements")
        if not isinstance(records, list):
            raise ValueError("Execution document needs a measurements list")
        state = document.get("state")
        if kind == "hpc_execution":
            if state not in {"prepared", "running", "completed"}:
                raise ValueError("Unknown HPC execution state")
            if records and state == "prepared":
                raise ValueError("Prepared HPC documents cannot contain measurements")
        elif records and state != "collected":
            raise ValueError("Only collected execution documents may contain measurements")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Execution measurements must be complete record objects")
            validate_run_record(record)
            if (record["experiment_kind"] == "convergence_summary"
                    or record["experiment_type"] == "hpc_submission"
                    or not record["sweep"]["values"]):
                raise ValueError("Execution measurements must contain completed measurement grids")
        identifiers = [record["record_id"] for record in records]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Execution measurement record_id values must be unique")
        return records
    validate_run_record(document)
    return [document]


def load_runs(filepath: str | Path, *, include_summaries: bool = False) -> list[dict[str, Any]]:
    """Read all logical measurements in one physical JSON, parsing it once.

    Pending executions return an empty list. Completed tasks in a running HPC
    document remain available. Rounded summaries are optional.
    """
    document = _read_document(filepath)
    return [_run_view(record, filepath, document) for record in _measurements(document)
            if include_summaries or record["experiment_kind"] != "convergence_summary"]


def load_run(filepath: str | Path, *, record_id: str | None = None) -> dict[str, Any]:
    """Read one result, selecting a case by record_id for jobs with multiple cases.

    Every returned filepath names the physical JSON file. Execution provenance is
    available in execution_record; no sidecar or external configuration is read.
    """
    document = _read_document(filepath)
    records = _measurements(document)
    if record_id is not None:
        records = [record for record in records if record["record_id"] == record_id]
    if not records:
        raise ValueError(f"No matching measured record in {filepath}")
    if len(records) != 1:
        raise ValueError(f"Multiple measurements in {filepath}; specify record_id")
    return _run_view(records[0], filepath, document)


def _run_view(raw: dict[str, Any], filepath: str | Path,
              document: dict[str, Any] | None = None) -> dict[str, Any]:
    if raw["experiment_kind"] == "convergence_summary":
        return {**raw, "filepath": str(filepath), "filename": Path(filepath).name}
    proto = raw["protocol"]
    sweep = raw["sweep"]
    theta_samples = proto["theta_samples"]
    per_theta = raw.get("per_theta_fidelities")
    counts_grid = raw.get("counts")
    entries = []
    sweep_key = "tau" if sweep["axis"] == "tau" else sweep["axis"]
    for ti, thetas in enumerate(theta_samples):
        for j, value in enumerate(sweep["values"]):
            if per_theta is not None:
                fids = per_theta[ti][j]
            elif ti == 0:
                fids = raw["fidelities"][j]
            else:
                continue
            entry = {"theta_idx": ti, "thetas": thetas, sweep_key: value, "fidelities": fids}
            if counts_grid is not None:
                entry["counts"] = counts_grid[ti][j]
            entries.append(entry)
    run = dict(raw)
    run.update(
        filepath=str(filepath), filename=Path(filepath).name,
        M=proto["M"], N=proto["N"], alpha=proto.get("alpha"),
        use_qec=proto.get("use_qec"), theta_samples=theta_samples, nt=len(theta_samples),
        linear_feedforward=proto.get("linear_feedforward"), outcomes_list=proto.get("outcomes_list"),
        tau_values=sweep["values"] if sweep["axis"] == "tau" else [],
        p_list=sweep["values"] if sweep["axis"] == "p" else [], entries=entries,
    )
    if raw["experiment_kind"] == "memory":
        run["state_prep"] = proto["state_prep"]
        ideal = (raw.get("reference_fidelities") or {}).get("ideal")
        run["ideal_fidelities"] = None if ideal is None else [row[0] for row in ideal]
    if document and document.get("document_type") in _EXECUTION_DOCUMENT_TYPES:
        run["execution_record"] = {key: value for key, value in document.items()
                                   if key != "measurements"}
    return run


def run_paths(results_dir: str | Path = RESULTS_DIR, *,
              include_summaries: bool = False) -> list[Path]:
    """Find physical result JSON files directly inside the flat results directory."""
    paths = []
    for path in sorted(Path(results_dir).glob("*.json")):
        document = _read_document(path)
        if document.get("document_type") in _EXECUTION_DOCUMENT_TYPES:
            if _measurements(document):
                paths.append(path)
        elif document.get("experiment_kind") in {"broadcasting", "memory"}:
            validate_run_record(document)
            paths.append(path)
        elif include_summaries and document.get("experiment_kind") == "convergence_summary":
            validate_run_record(document)
            paths.append(path)
    return paths


def list_runs(results_dir: str | Path = RESULTS_DIR, *,
              experiment_kind: str | None = None,
              experiment_type: str | None = None, backend: str | None = None,
              include_summaries: bool = False) -> list[dict[str, Any]]:
    """Load logical measurements, expanding collected jobs into distinct cases.

    Rounded convergence summaries are optional and never treated as measurements.
    """
    summaries = include_summaries or experiment_kind == "convergence_summary"
    runs = []
    for path in sorted(Path(results_dir).glob("*.json")):
        document = _read_document(path)
        if (document.get("document_type") not in _EXECUTION_DOCUMENT_TYPES
                and document.get("experiment_kind") not in {"broadcasting", "memory", "convergence_summary"}):
            continue
        if document.get("experiment_kind") == "convergence_summary" and not summaries:
            continue
        for record in _measurements(document):
            if record["experiment_kind"] == "convergence_summary" and not summaries:
                continue
            if ((experiment_kind is None or record["experiment_kind"] == experiment_kind)
                    and (experiment_type is None or record["experiment_type"] == experiment_type)
                    and (backend is None or record.get("backend") == backend)):
                runs.append(_run_view(record, path, document))
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
