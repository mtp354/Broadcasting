"""Prepare immutable hardware experiments, submit once, and recover by job ID.

Planning and status are offline. Only prepare, submit, collect and attach-job
create a Runtime service. Each repeat is a separate job with seeded, interleaved
PUB order. Identical phases reuse compiled circuits; different repeat phases
get their own archived circuits with a shared initial layout. Submitted
order is recorded but does not guarantee the provider's chronological execution.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import uuid

from .backend import HardwareBackend, _sampler_settings
from .protocol import ProtocolConfig
from .provenance import calibration_provenance
from .results import save_run, save_memory_run, load_run, write_run_json


DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "records"


COMMON_CONFIG_KEYS = {
    "schema_version", "experiment_id", "runtime_account", "backend", "shots",
    "repeats", "seed", "seed_transpiler", "optimization_level", "alpha",
    "tau_values_dt", "cases",
}
CASE_KEYS = {"id", "M", "N", "receiver_delay_factors", "initial_layout"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
ORDER_NOTE = "Submitted PUB order is archived; device chronological order is not guaranteed. See Runtime execution spans when available."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _integer(value, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")
    return value


def _finite(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number.")
    return value


def _keys(data, allowed, name):
    if not isinstance(data, dict) or set(data) != allowed:
        raise ValueError(f"{name} must contain exactly: {', '.join(sorted(allowed))}.")


def validate_config(config: dict, *, online: bool = False) -> dict:
    """Reject mistakes before account lookup or creating a run directory."""
    if isinstance(config, dict) and config.get("experiment_kind") == "memory":
        return _validate_memory_config(config, online=online)
    if (not isinstance(config, dict) or type(config.get("schema_version")) is not int
            or config["schema_version"] not in (1, 2)):
        raise ValueError("Unsupported experiment schema_version; supported versions are 1 and 2.")
    phase_key = "theta_samples" if config["schema_version"] == 1 else "phase_design"
    _keys(config, COMMON_CONFIG_KEYS | {phase_key}, "Experiment")
    if not isinstance(config["experiment_id"], str) or not IDENTIFIER.fullmatch(config["experiment_id"]):
        raise ValueError("experiment_id must be a short filename-safe identifier.")
    for key in ("runtime_account", "backend"):
        value = config[key]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"{key} must be an explicit nonempty name.")
        if online and value == "EDIT_ME":
            raise ValueError(f"Set {key} in the config before preparing hardware.")
    for key in ("shots", "repeats"):
        _integer(config[key], key, 1)
    for key in ("seed", "seed_transpiler", "optimization_level"):
        _integer(config[key], key)
    if config["optimization_level"] > 3:
        raise ValueError("optimization_level must be between 0 and 3.")
    if not -1 <= _finite(config["alpha"], "alpha") <= 1:
        raise ValueError("alpha must be in [-1, 1].")
    if not isinstance(config["tau_values_dt"], list):
        raise ValueError("tau_values_dt must be a list.")
    HardwareBackend._validate_taus(config["tau_values_dt"])
    if not isinstance(config["cases"], list) or not config["cases"]:
        raise ValueError("cases must be a nonempty list.")
    ids, conditions, layouts = set(), set(), {}
    for case in config["cases"]:
        _keys(case, CASE_KEYS, "Case")
        if not isinstance(case["id"], str) or not IDENTIFIER.fullmatch(case["id"]) or case["id"] in ids:
            raise ValueError("Each case id must be unique and filename-safe.")
        ids.add(case["id"])
        for key in ("M", "N"):
            _integer(case[key], key, 1)
        factors = case["receiver_delay_factors"]
        if not isinstance(factors, list) or len(factors) != case["N"]:
            raise ValueError("receiver_delay_factors must have N entries.")
        for factor in factors:
            _integer(factor, "receiver_delay_factors")
        if not any(factors):
            raise ValueError("At least one receiver delay factor must be positive.")
        layout = case["initial_layout"]
        if layout is not None:
            n_qubits = case["M"] * math.ceil(math.log2(case["N"] + 1)) + case["N"]
            if not isinstance(layout, list) or len(layout) != n_qubits:
                raise ValueError(f"initial_layout must contain {n_qubits} physical indices for {case['id']}.")
            for qubit in layout:
                _integer(qubit, "initial_layout")
            if len(set(layout)) != len(layout):
                raise ValueError("initial_layout must contain unique qubit indices.")
            size = (case["M"], case["N"])
            if size in layouts and layouts[size] != layout:
                raise ValueError("Matched M,N cases must use the same initial_layout.")
            layouts[size] = layout
        signature = (case["M"], case["N"], tuple(factors))
        if signature in conditions:
            raise ValueError("Duplicate case conditions; use repeats for independent repeats.")
        conditions.add(signature)
    _validate_phases(config)
    return config


def _validate_samples(samples, senders):
    if (not isinstance(samples, list) or not samples or
            any(not isinstance(row, list) or len(row) != senders for row in samples)):
        raise ValueError(f"Each theta sample must have M={senders} entries.")
    for row in samples:
        for theta in row:
            _finite(theta, "theta")
    if len({tuple(row) for row in samples}) != len(samples):
        raise ValueError("theta samples must not contain duplicate samples.")


def _validate_phases(config):
    senders = {case["M"] for case in config["cases"]}
    if config["schema_version"] == 1:
        for m in senders:
            _validate_samples(config["theta_samples"], m)
        return
    design = config["phase_design"]
    if not isinstance(design, dict):
        raise ValueError("phase_design must be a dictionary.")
    if design.get("kind") == "seeded_random":
        _keys(design, {"kind", "seed", "samples_per_repeat", "low", "high"}, "Random phase design")
        _integer(design["seed"], "phase seed")
        _integer(design["samples_per_repeat"], "samples_per_repeat", 1)
        if _finite(design["low"], "low") >= _finite(design["high"], "high"):
            raise ValueError("phase low must be less than high.")
    elif design.get("kind") == "fixed":
        _keys(design, {"kind", "samples_by_m"}, "Fixed phase design")
        samples = design["samples_by_m"]
        if not isinstance(samples, dict) or set(samples) != {str(m) for m in senders}:
            raise ValueError("samples_by_m must contain exactly the configured sender counts as string keys.")
        for m in senders:
            _validate_samples(samples[str(m)], m)
        if len({len(rows) for rows in samples.values()}) != 1:
            raise ValueError("Every sender count must have the same number of theta samples.")
    else:
        raise ValueError("phase_design kind must be seeded_random or fixed.")


def _phase_schedule(config):
    """Draw a full sender vector once per repeat/sample and share prefixes across N."""
    if config["schema_version"] == 1:
        return [{"kind": "fixed", "phase_seed": None,
                 "theta_samples_by_case": [config["theta_samples"] for _ in config["cases"]]}
                for _ in range(config["repeats"])]
    design = config["phase_design"]
    if design["kind"] == "fixed":
        return [{"kind": "fixed", "phase_seed": None,
                 "theta_samples_by_case": [design["samples_by_m"][str(case["M"])] for case in config["cases"]]}
                for _ in range(config["repeats"])]
    rng = random.Random(design["seed"])
    largest_m = max(case["M"] for case in config["cases"])
    schedule = []
    for _ in range(config["repeats"]):
        vectors = [[rng.uniform(design["low"], design["high"]) for _ in range(largest_m)]
                   for _ in range(design["samples_per_repeat"])]
        schedule.append({"kind": "seeded_random", "phase_seed": design["seed"],
                         "theta_samples_by_case": [[row[:case["M"]] for row in vectors]
                                                   for case in config["cases"]]})
    return schedule


def make_experiment_config(kind: str, *, runtime_account="EDIT_ME", backend="EDIT_ME",
                         experiment_id=None, repeats=3, seed=20260908,
                         sender_counts=(1, 2, 3), receiver_counts=(1, 2, 3, 4),
                         tau_values_dt=None) -> dict:
    """Build editable notebook defaults; this function is entirely offline.

    Delay repeats use M=1,N=2 and 10,000 shots at each of 121 delays.
    Scaling uses the explicit sender/receiver matrix and 8,192 shots at zero delay.
    Both vary phases across repeats and share phases across N within a repeat.
    """
    if kind not in ("delay", "scaling"):
        raise ValueError("kind must be delay or scaling.")
    pairs = [(1, 2)] if kind == "delay" else [(m, n) for m in sender_counts for n in receiver_counts]
    config = {
        "schema_version": 2, "experiment_id": experiment_id or f"broadcasting-{kind}-repeats",
        "runtime_account": runtime_account, "backend": backend,
        "shots": 10000 if kind == "delay" else 8192, "repeats": repeats,
        "seed": seed, "seed_transpiler": seed, "optimization_level": 3,
        "alpha": 1 / math.sqrt(2),
        "phase_design": {"kind": "seeded_random", "seed": seed + 1,
                         "samples_per_repeat": 1, "low": 0.0, "high": 2 * math.pi},
        "tau_values_dt": (list(range(0, 6001, 50)) if kind == "delay" else [0])
                         if tau_values_dt is None else list(tau_values_dt),
        "cases": [{"id": f"m{m}_n{n}", "M": m, "N": n,
                   "receiver_delay_factors": [1] * n, "initial_layout": None} for m, n in pairs],
    }
    return validate_config(config)


def read_config(path: str | Path) -> dict:
    return validate_config(json.loads(Path(path).read_text()))


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def plan_experiment(config: dict) -> dict:
    """Seeded block randomization interleaves every case at each theta/delay."""
    validate_config(config)
    if config.get("experiment_kind") == "memory":
        return _memory_plan(config)
    rng = random.Random(config["seed"])
    phases = _phase_schedule(config)
    points = [(ti, di) for ti in range(len(phases[0]["theta_samples_by_case"][0]))
              for di in range(len(config["tau_values_dt"]))]
    repeats = []
    for repeat in range(config["repeats"]):
        block_order = points.copy()
        rng.shuffle(block_order)
        order = []
        for ti, di in block_order:
            case_order = list(range(len(config["cases"])))
            rng.shuffle(case_order)
            for ci in case_order:
                order.append({"case_index": ci, "case_id": config["cases"][ci]["id"],
                              "theta_index": ti, "tau_index": di,
                              "tau_dt": config["tau_values_dt"][di],
                              "canonical_index": ti * len(config["tau_values_dt"]) + di})
        entry = {"repeat_index": repeat, "pub_order": order}
        if config["schema_version"] == 2:
            entry["phases"] = phases[repeat]
            for pub in order:
                pub["thetas"] = phases[repeat]["theta_samples_by_case"][pub["case_index"]][pub["theta_index"]]
        repeats.append(entry)
    pubs = len(points) * len(config["cases"])
    cases = [{"id": case["id"], "M": case["M"], "N": case["N"],
              "logical_qubits": case["M"] * math.ceil(math.log2(case["N"] + 1)) + case["N"],
              "shots_per_repeat": len(points) * config["shots"]} for case in config["cases"]]
    return {"experiment_id": config["experiment_id"], "backend": config["backend"],
            "runtime_account": config["runtime_account"], "config_sha256": _digest(config),
            "jobs": config["repeats"], "pubs_per_job": pubs,
            "total_pubs": pubs * config["repeats"],
            "total_shots": pubs * config["repeats"] * config["shots"],
            "shots_per_pub": config["shots"], "optimization_level": config["optimization_level"],
            "cases": cases, "phase_design": config.get("phase_design", {"kind": "fixed"}),
            "order_note": ORDER_NOTE, "repeats": repeats}


def _service(config):
    from qiskit_ibm_runtime import QiskitRuntimeService
    return QiskitRuntimeService(name=config["runtime_account"])


def _durable_json(data, path):
    parent_created = not Path(path).parent.exists()
    path = write_run_json(data, path)
    # Persist the new receipts/attempts directory entry as well as its file.
    directories = [path.parent, path.parent.parent] if parent_created else [path.parent]
    for directory in directories:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return path


@contextmanager
def _locked(run_dir):
    # The file remains; flock is released automatically after crashes. All
    # experiment mutations hold this lock, including the brief submit/receipt gap.
    with (Path(run_dir) / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def prepare_experiment(config: dict, run_dir: str | Path, *, service=None, results_dir=None) -> dict:
    """Freeze all compiled circuits and calibration before any submission."""
    validate_config(config, online=True)
    if config.get("experiment_kind") == "memory":
        return _prepare_memory(config, run_dir, service=service, results_dir=results_dir)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    plan = plan_experiment(config)
    _durable_json({"config": config, "plan": plan}, run_dir / "plan.json")
    service = _service(config) if service is None else service
    backend = service.backend(config["backend"])
    dt = getattr(getattr(backend, "target", None), "dt", None)
    if dt is None or not math.isfinite(dt) or dt <= 0:
        raise ValueError("Backend must publish a positive dt before preparing this dt-based experiment.")
    target = backend.target
    delay_step = math.lcm(getattr(target, "granularity", 1) or 1,
                          getattr(target, "pulse_alignment", 1) or 1)
    if any(tau % delay_step for tau in config["tau_values_dt"]):
        raise ValueError(f"This backend requires delays in multiples of {delay_step} dt. "
                         "Edit tau_values_dt explicitly and prepare a new directory; delays are never rounded.")
    for case in plan["cases"]:
        if case["logical_qubits"] > backend.num_qubits:
            raise ValueError(f"{case['id']} needs {case['logical_qubits']} qubits; backend has {backend.num_qubits}.")
    cases = []
    circuit_review = []
    shared_layouts = {}
    for case in config["cases"]:
        key = (case["M"], case["N"])
        if case["initial_layout"] is not None:
            if key in shared_layouts and shared_layouts[key] != case["initial_layout"]:
                raise ValueError("Matched M,N cases must use the same initial_layout.")
            shared_layouts[key] = case["initial_layout"]
    # Prepare each distinct case/phase pair once. v1 fixed-phase bundles retain
    # their original cases layout; v2 records the template chosen for each repeat.
    phases = _phase_schedule(config)
    template_cache, repeat_case_indices = {}, []
    mapping_review, receiver_mappings = [], {}
    for ri, phase in enumerate(phases):
        indices = []
        for ci, case in enumerate(config["cases"]):
            samples = phase["theta_samples_by_case"][ci]
            signature = (ci, tuple(tuple(row) for row in samples))
            if signature not in template_cache:
                key = (case["M"], case["N"])
                hardware = HardwareBackend(
                    service, config["backend"], shots=config["shots"],
                    optimization_level=config["optimization_level"],
                    seed_transpiler=config["seed_transpiler"], initial_layout=shared_layouts.get(key),
                )
                protocol = ProtocolConfig(M=case["M"], N=case["N"], alpha=config["alpha"],
                                          thetas=samples[0], use_qec=False)
                compiled = hardware.prepare_tau_sweep(
                    protocol, config["tau_values_dt"], theta_samples=samples,
                    receiver_delay_factors=case["receiver_delay_factors"], backend=backend,
                )
                shared_layouts[key] = compiled["metadata"]["initial_layout"]
                template_cache[signature] = len(cases)
                cases.append(compiled)
                depths = [row["depth"] for row in compiled["metadata"]["compiled_circuits"]]
                circuit_review.append({"case_id": case["id"], "first_repeat_index": ri,
                                       "theta_samples": samples, "depth_min": min(depths),
                                       "depth_max": max(depths),
                                       "pubs": len(compiled["metadata"]["compiled_circuits"]),
                                       "compilation": compiled["metadata"]["compilation"]})
                for index, archived in enumerate(compiled["metadata"]["compiled_circuits"]):
                    layout = archived["layout"]
                    mapping = layout["final_index_layout"][-case["N"]:] if layout else None
                    mapping_review.append({"case_id": case["id"], "first_repeat_index": ri,
                                           "prepared_case_index": len(cases) - 1,
                                           "canonical_index": index, "receiver_output_qubits": mapping})
                    receiver_mappings.setdefault(key, set()).add(tuple(mapping) if mapping else None)
            indices.append(template_cache[signature])
        repeat_case_indices.append(indices)
    warnings = [f"M={m},N={n}: receiver output mappings differ between compiled conditions; inspect mapping_review before comparing controls."
                for (m, n), mappings in receiver_mappings.items() if len(mappings) > 1 or None in mappings]
    prepared = {"schema_version": config["schema_version"], "run_id": uuid.uuid4().hex,
                "prepared_at": _now(), "config": config, "plan": plan, "cases": cases,
                "results_dir": str(Path(results_dir or DEFAULT_RESULTS_DIR).resolve()),
                "review": {"dt_seconds": dt, "required_delay_step_dt": delay_step,
                           "circuit_review": circuit_review,
                           "delay_seconds": [tau * dt for tau in config["tau_values_dt"]],
                           "shared_initial_layouts": {f"M{m}N{n}": layout for (m, n), layout in shared_layouts.items()},
                           "mapping_review": mapping_review, "comparison_warnings": warnings}}
    if config["schema_version"] == 2:
        prepared["repeat_case_indices"] = repeat_case_indices
    _durable_json(prepared, run_dir / "prepared.json")
    _durable_json({"sha256": _digest(prepared)}, run_dir / "prepared.sha256.json")
    return prepared


def load_prepared_experiment(run_dir, *, expected_config=None):
    """Read and validate a frozen bundle offline, including its checksum."""
    run_dir = Path(run_dir)
    prepared = json.loads((run_dir / "prepared.json").read_text())
    checksum = json.loads((run_dir / "prepared.sha256.json").read_text())["sha256"]
    if _digest(prepared) != checksum or _digest(prepared["config"]) != prepared["plan"]["config_sha256"]:
        raise ValueError("Prepared experiment checksum mismatch; prepare a new directory for changes.")
    # Recovery bundles preserve their original bytes and checksum. Normalize old
    # field names only after verifying the archived preparation above.
    if "campaign_id" in prepared["config"]:
        prepared["config"]["experiment_id"] = prepared["config"].pop("campaign_id")
        prepared["plan"]["experiment_id"] = prepared["plan"].pop("campaign_id")
    validate_config(prepared["config"], online=True)
    if prepared["schema_version"] != prepared["config"]["schema_version"]:
        raise ValueError("Prepared bundle/config schema versions do not match.")
    if prepared["schema_version"] == 2 and prepared["config"].get("experiment_kind") != "memory":
        mapping = prepared.get("repeat_case_indices")
        if (not isinstance(mapping, list) or len(mapping) != prepared["config"]["repeats"] or
                any(not isinstance(row, list) or len(row) != len(prepared["config"]["cases"]) or
                    any(type(index) is not int or not 0 <= index < len(prepared["cases"]) for index in row)
                    for row in mapping)):
            raise ValueError("Invalid repeat/case mapping in prepared v2 bundle.")
    if expected_config is not None and prepared["config"] != validate_config(expected_config):
        raise ValueError("Notebook/config differs from this frozen preparation. Restore the original config or use a new run directory.")
    return prepared


def _receipt_path(run_dir, repeat):
    return Path(run_dir) / "receipts" / f"repeat_{repeat:03d}.json"


def _attempt_path(run_dir, repeat):
    return Path(run_dir) / "attempts" / f"repeat_{repeat:03d}.json"


def _tags(prepared, repeat):
    return [f"broadcast-{prepared['run_id']}", f"repeat-{repeat:03d}"]


def _load_record(run_dir, prepared, repeat, *, receipt=False):
    """Reject misplaced or edited local records before trusting a job ID."""
    path = _receipt_path(run_dir, repeat) if receipt else _attempt_path(run_dir, repeat)
    record = json.loads(path.read_text())
    order = prepared["plan"]["repeats"][repeat]["pub_order"]
    expected = {"run_id": prepared["run_id"], "repeat_index": repeat,
                "shots": prepared["config"]["shots"], "job_tags": _tags(prepared, repeat),
                "intended_pub_order": order}
    if receipt:
        expected["submitted_pub_order"] = order
        if not isinstance(record.get("job_id"), str) or not record["job_id"].strip():
            raise ValueError(f"Invalid job ID in {path}.")
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError(f"Record does not match the prepared experiment: {path}.")
    return record


def _result_path(run_dir, repeat, case, prepared):
    key = f"repeat_{repeat:03d}_{case['id']}.json"
    mapping_path = Path(run_dir) / "output_paths.json"
    if mapping_path.exists():
        mapping = json.loads(mapping_path.read_text())
        if key in mapping:
            path = Path(mapping[key])
            return path if path.is_absolute() else Path(__file__).resolve().parent.parent / path
    directory = Path(prepared.get("results_dir", DEFAULT_RESULTS_DIR))
    return directory / f"{prepared['config']['experiment_id']}_{prepared['run_id']}_{key}"


def _case_pub_indices(order, case_index):
    return sorted((index for index, pub in enumerate(order) if pub["case_index"] == case_index),
                  key=lambda index: order[index]["canonical_index"])


def _validated_result_exists(path, prepared, receipt, case_index):
    """Trust a completed filename only after checking its identity and data grid."""
    if not path.exists():
        return False
    if prepared["config"].get("experiment_kind") == "memory":
        return _validated_memory_result(path, prepared, receipt)
    config = prepared["config"]
    repeat = receipt["repeat_index"]
    case = config["cases"][case_index]
    compiled = _prepared_case(prepared, repeat, case_index)
    samples = compiled["metadata"]["theta_samples"]
    expected_experiment = {
        "experiment_id": config["experiment_id"], "run_id": prepared["run_id"],
        "repeat_index": repeat, "case_id": case["id"],
        "config_sha256": prepared["plan"]["config_sha256"],
        "receiver_delay_factors": case["receiver_delay_factors"],
        "submitted_pub_indices": _case_pub_indices(receipt["submitted_pub_order"], case_index),
    }
    extra_experiment = {"case_index": case_index, "job_id": receipt["job_id"],
                      "theta_samples": samples, "phase_design": config.get("phase_design", {"kind": "fixed"}),
                      "phase_seed": config.get("phase_design", {}).get("seed")}
    try:
        run = json.loads(path.read_text())
        experiment = run["metadata"]["execution"]
        # Original v1 results predate the redundant phase/job fields. Their
        # protocol and receipt still supply these identities; validate any
        # additional fields when present and require them for v2 results.
        expected_experiment.update({key: value for key, value in extra_experiment.items()
                                  if prepared["schema_version"] == 2 or key in experiment})
        checks = [
            (run, {"experiment_type": "hardware", "job_id": receipt["job_id"],
                   "backend": config["backend"], "shots": config["shots"],
                   "optimization_level": config["optimization_level"]}),
            (run["protocol"], {"M": case["M"], "N": case["N"], "alpha": config["alpha"],
                               "use_qec": False, "theta_samples": samples}),
            (run["sweep"], {"axis": "tau", "values": config["tau_values_dt"]}),
            (experiment, expected_experiment),
            (run["metadata"]["execution"], {key: receipt[key] for key in
             ("job_id", "run_id", "repeat_index", "shots", "submitted_pub_order")}),
        ]
        if any(actual.get(key) != value for actual, expected in checks for key, value in expected.items()):
            raise ValueError("identity, configuration, phase, or submitted order differs")
        counts = run["counts"]
        if len(counts) != len(samples) or any(len(row) != len(config["tau_values_dt"]) for row in counts):
            raise ValueError("incomplete theta/delay count grid")
        for row in counts:
            for histogram in row:
                if (not isinstance(histogram, dict) or sum(histogram.values()) != config["shots"] or
                        any(not isinstance(bits, str) or len(bits) != case["N"] or set(bits) - {"0", "1"}
                            or type(count) is not int or count < 0 for bits, count in histogram.items())):
                    raise ValueError("malformed counts or shot count differs")
        fidelities = run["fidelities"]
        if len(fidelities) != len(config["tau_values_dt"]) or any(len(row) != case["N"] for row in fidelities):
            raise ValueError("incomplete fidelity grid")
        for di, values in enumerate(fidelities):
            local = [HardwareBackend._fidelities_from_counts(row[di], case["N"]) for row in counts]
            if any(not math.isclose(value, sum(row[receiver] for row in local) / len(samples),
                                    rel_tol=0, abs_tol=1e-12) for receiver, value in enumerate(values)):
                raise ValueError("fidelities disagree with saved counts")
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"Saved result does not match its prepared experiment: {path} ({exc}). "
                         "Restore the original file or move it aside before collecting again; it will not be overwritten.") from exc
    return True


def experiment_status(run_dir: str | Path) -> dict:
    """Report durable local state without contacting IBM."""
    prepared = load_prepared_experiment(run_dir)
    states = []
    for repeat in range(prepared["config"]["repeats"]):
        receipt = _receipt_path(run_dir, repeat)
        attempt = _attempt_path(run_dir, repeat)
        state = "unsubmitted"
        job_id = None
        if receipt.exists():
            _load_record(run_dir, prepared, repeat)
            record = _load_record(run_dir, prepared, repeat, receipt=True)
            job_id = record["job_id"]
            count = sum(_validated_result_exists(_result_path(run_dir, repeat, case, prepared), prepared, record, ci)
                        for ci, case in enumerate(prepared["config"]["cases"]))
            state = "collected" if count == len(prepared["config"]["cases"]) else "submitted"
        elif attempt.exists():
            _load_record(run_dir, prepared, repeat)
            state = "ambiguous: reconcile the attempt; submission will not retry"
        states.append({"repeat_index": repeat, "state": state, "job_id": job_id})
    return {"run_id": prepared["run_id"], "experiment_id": prepared["config"]["experiment_id"], "repeats": states}


def _prepared_case(prepared, repeat, case_index):
    if prepared["config"].get("experiment_kind") == "memory":
        return prepared["cases"][0]
    index = (prepared["repeat_case_indices"][repeat][case_index]
             if prepared["schema_version"] == 2 else case_index)
    return prepared["cases"][index]


def _ordered_circuits(prepared, order, repeat):
    if prepared["config"].get("experiment_kind") == "memory":
        circuits = HardwareBackend.replay_prepared(prepared["cases"][0])
        return [circuits[pub["canonical_index"]] for pub in order]
    circuits = [HardwareBackend.replay_prepared(_prepared_case(prepared, repeat, ci))
                for ci in range(len(prepared["config"]["cases"]))]
    return [circuits[pub["case_index"]][pub["canonical_index"]] for pub in order]


def submit_experiment(run_dir: str | Path, *, service=None, sampler_factory=None) -> list[str]:
    """Submit only never-attempted repeats; save each job ID before continuing."""
    with _locked(run_dir):
        prepared = load_prepared_experiment(run_dir)
        config = prepared["config"]
        for repeat in range(config["repeats"]):
            if _receipt_path(run_dir, repeat).exists():
                _load_record(run_dir, prepared, repeat, receipt=True)
                _load_record(run_dir, prepared, repeat)
            elif _attempt_path(run_dir, repeat).exists():
                _load_record(run_dir, prepared, repeat)
            if _attempt_path(run_dir, repeat).exists() and not _receipt_path(run_dir, repeat).exists():
                raise ValueError(f"Repeat {repeat} has an ambiguous submission. Use attach-job after identifying its tagged job; do not retry.")
        pending = [repeat for repeat in prepared["plan"]["repeats"]
                   if not _receipt_path(run_dir, repeat["repeat_index"]).exists()]
        if not pending:
            return []
        service = _service(config) if service is None else service
        backend = service.backend(config["backend"])
        dt = getattr(getattr(backend, "target", None), "dt", None)
        if dt != prepared["cases"][0]["metadata"]["dt"]:
            raise ValueError("Backend dt changed since preparation; prepare a new cohort.")
        jobs = []
        for repeat in pending:
            ri, order = repeat["repeat_index"], repeat["pub_order"]
            circuits = _ordered_circuits(prepared, order, ri)
            HardwareBackend._validate_target(circuits, backend)
            if sampler_factory is None:
                from qiskit_ibm_runtime import SamplerV2
                sampler = SamplerV2(mode=backend, options={"environment": {"job_tags": _tags(prepared, ri)}})
            else:
                sampler = sampler_factory(backend, _tags(prepared, ri))
            attempt = {"run_id": prepared["run_id"], "repeat_index": ri,
                       "attempted_at": _now(), "job_tags": _tags(prepared, ri),
                       "intended_pub_order": order, "shots": config["shots"],
                       "sampler_options": _sampler_settings(sampler),
                       "submission_calibration": calibration_provenance(backend, circuits)}
            _durable_json(attempt, _attempt_path(run_dir, ri))
            job = sampler.run([(circuit,) for circuit in circuits], shots=config["shots"])
            job_id = job.job_id()
            _durable_json({**attempt, "job_id": job_id, "submitted_at": _now(),
                           "submitted_pub_order": order, "actual_device_order_note": ORDER_NOTE},
                          _receipt_path(run_dir, ri))
            print(f"Repeat {ri}: saved job ID {job_id}", flush=True)
            jobs.append(job_id)
        return jobs


def _verify_job(job, prepared, repeat, circuits):
    """Check recovered job identity and exact submitted circuits before linking."""
    if not set(_tags(prepared, repeat)).issubset(set(job.tags)):
        raise ValueError("Job tags do not match this run and repeat.")
    if job.backend().name != prepared["config"]["backend"]:
        raise ValueError("Job backend does not match the prepared experiment.")
    from qiskit.primitives.containers.sampler_pub import SamplerPub
    inputs = job.inputs
    pubs = [SamplerPub.coerce(pub, shots=inputs.get("options", {}).get("default_shots"))
            for pub in inputs["pubs"]]
    if len(pubs) != len(circuits) or any(pub.circuit != circuit or pub.parameter_values.num_parameters
                                        for pub, circuit in zip(pubs, circuits)):
        raise ValueError("Job PUB circuits/order do not match the archived preparation.")
    if any(pub.shots != prepared["config"]["shots"] for pub in pubs):
        raise ValueError("Job shots do not match the experiment.")


def attach_job(run_dir, repeat: int, job_id: str, *, service=None):
    """Recover an interrupted submit by explicitly linking its matching job ID."""
    with _locked(run_dir):
        prepared = load_prepared_experiment(run_dir)
        _integer(repeat, "repeat")
        if repeat >= prepared["config"]["repeats"]:
            raise ValueError("repeat index is outside this experiment.")
        if _receipt_path(run_dir, repeat).exists():
            raise FileExistsError("This repeat already has a receipt.")
        attempt = _load_record(run_dir, prepared, repeat)
        service = _service(prepared["config"]) if service is None else service
        job = service.job(job_id)
        order = prepared["plan"]["repeats"][repeat]["pub_order"]
        _verify_job(job, prepared, repeat, _ordered_circuits(prepared, order, repeat))
        return _durable_json({**attempt, "job_id": job_id, "recovered_at": _now(),
                              "submitted_pub_order": order, "actual_device_order_note": ORDER_NOTE},
                             _receipt_path(run_dir, repeat))


def collect_experiment(run_dir: str | Path, *, service=None) -> list[Path]:
    """Retrieve known jobs by ID, preserving each repeat and case separately."""
    with _locked(run_dir):
        prepared = load_prepared_experiment(run_dir)
        config = prepared["config"]
        receipts = []
        for ri in range(config["repeats"]):
            if _receipt_path(run_dir, ri).exists():
                _load_record(run_dir, prepared, ri)
                receipts.append(_load_record(run_dir, prepared, ri, receipt=True))
        pending = []
        for receipt in receipts:
            outputs = [_result_path(run_dir, receipt["repeat_index"], case, prepared) for case in config["cases"]]
            complete = [_validated_result_exists(path, prepared, receipt, ci) for ci, path in enumerate(outputs)]
            if not all(complete):
                pending.append((receipt, outputs, complete))
        if not pending:
            return []
        service = _service(config) if service is None else service
        paths = []
        for receipt, outputs, complete in pending:
            ri = receipt["repeat_index"]
            job = service.job(receipt["job_id"])
            order = receipt["submitted_pub_order"]
            _verify_job(job, prepared, ri, _ordered_circuits(prepared, order, ri))
            container = job.result()
            results = list(container)
            if len(results) != len(order):
                raise ValueError("Job returned a different number of PUB results than submitted.")
            if config.get("experiment_kind") == "memory":
                paths.append(_save_memory_result(prepared, receipt, container, outputs[0]))
                continue
            for ci, (case, output) in enumerate(zip(config["cases"], outputs)):
                if complete[ci]:
                    continue
                indices = _case_pub_indices(order, ci)
                compiled_case = _prepared_case(prepared, ri, ci)
                result = HardwareBackend.collect_prepared(
                    compiled_case, [results[index] for index in indices], job_id=receipt["job_id"],
                    execution={**receipt, "collected_at": _now()},
                )
                # Full-container metadata includes execution spans for all PUBs.
                from qiskit_ibm_runtime import RuntimeEncoder
                result.metadata["execution"]["sampler_result_metadata"] = json.loads(json.dumps(
                    getattr(container, "metadata", None), cls=RuntimeEncoder))
                result.metadata["execution"].update({
                    "experiment_id": config["experiment_id"], "run_id": prepared["run_id"],
                    "repeat_index": ri, "case_id": case["id"],
                    "config_sha256": prepared["plan"]["config_sha256"],
                    "receiver_delay_factors": case["receiver_delay_factors"],
                    "submitted_pub_indices": indices,
                    "phase_design": config.get("phase_design", {"kind": "fixed"}),
                    "phase_seed": config.get("phase_design", {}).get("seed"),
                    "theta_samples": compiled_case["metadata"]["theta_samples"],
                    "case_index": ci, "job_id": receipt["job_id"],
                })
                path = save_run(result, ProtocolConfig(**compiled_case["config"]), filepath=output)
                descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                paths.append(path)
        return paths


# The memory benchmark shares preparation, receipts, recovery, and collection
# with broadcasting. Only its circuit construction and measurement decoding differ.
def make_memory_config(*, runtime_account="EDIT_ME", backend="EDIT_ME",
                       experiment_id="qec-memory", use_qec=True, theta=0.7, phi=1.2,
                       tau_values_dt=None, shots=8192, optimization_level=0,
                       seed=42, repeats=1):
    """Editable single-qubit memory settings; entirely offline."""
    return validate_config({
        "schema_version": 2, "experiment_kind": "memory", "experiment_id": experiment_id,
        "runtime_account": runtime_account, "backend": backend,
        "use_qec": use_qec, "theta": theta, "phi": phi,
        "tau_values_dt": list(range(0, 6001, 300)) if tau_values_dt is None else list(tau_values_dt),
        "shots": shots, "optimization_level": optimization_level,
        "seed": seed, "seed_transpiler": seed, "repeats": repeats,
        "cases": [{"id": "memory"}],
    })


def _validate_memory_config(config, *, online=False):
    _keys(config, {"schema_version", "experiment_kind", "experiment_id", "runtime_account", "backend",
                   "use_qec", "theta", "phi", "tau_values_dt", "shots", "optimization_level",
                   "seed", "seed_transpiler", "repeats", "cases"}, "Memory experiment")
    if type(config["schema_version"]) is not int or config["schema_version"] != 2:
        raise ValueError("Memory experiments require schema_version 2.")
    if not isinstance(config["experiment_id"], str) or not IDENTIFIER.fullmatch(config["experiment_id"]):
        raise ValueError("experiment_id must be a short filename-safe identifier.")
    for key in ("runtime_account", "backend"):
        value = config[key]
        if not isinstance(value, str) or not value.strip() or value != value.strip() or (online and value == "EDIT_ME"):
            raise ValueError(f"Set an explicit {key} before preparing hardware.")
    for key in ("shots", "repeats"):
        _integer(config[key], key, 1)
    for key in ("seed", "seed_transpiler", "optimization_level"):
        _integer(config[key], key)
    if config["optimization_level"] > 3 or type(config["use_qec"]) is not bool:
        raise ValueError("Memory use_qec must be boolean and optimization_level must be between 0 and 3.")
    for key in ("theta", "phi"):
        _finite(config[key], key)
    if not isinstance(config["tau_values_dt"], list):
        raise ValueError("tau_values_dt must be a list.")
    HardwareBackend._validate_taus(config["tau_values_dt"])
    if config["cases"] != [{"id": "memory"}]:
        raise ValueError("Memory experiments contain exactly one memory case.")
    return config


def _memory_plan(config):
    count = len(config["tau_values_dt"])
    rng = random.Random(config["seed"])
    repeats = []
    for repeat in range(config["repeats"]):
        order = [{"case_index": 0, "case_id": "memory", "canonical_index": index,
                  "tau_index": index, "tau_dt": tau} for index, tau in enumerate(config["tau_values_dt"])]
        rng.shuffle(order)
        repeats.append({"repeat_index": repeat, "pub_order": order})
    return {"experiment_id": config["experiment_id"], "backend": config["backend"],
            "runtime_account": config["runtime_account"], "config_sha256": _digest(config),
            "jobs": config["repeats"], "pubs_per_job": count,
            "total_pubs": count * config["repeats"],
            "total_shots": count * config["repeats"] * config["shots"],
            "shots_per_pub": config["shots"], "optimization_level": config["optimization_level"],
            "cases": [{"id": "memory", "circuit_qubits": 9 if config["use_qec"] else 1}],
            "order_note": ORDER_NOTE, "repeats": repeats}


def build_memory_circuits(config):
    """Build the encoded or bare memory circuit and its bound delay sweeps."""
    from .qec_513 import qec_513_delay_benchmark_circuit
    validate_config(config)
    circuit, parameter, register = qec_513_delay_benchmark_circuit(
        config["theta"], config["phi"], use_qec=config["use_qec"])
    return circuit, [circuit.assign_parameters({parameter: tau}) for tau in config["tau_values_dt"]], register


def _memory_measurements(results, register, shots):
    histograms, fidelities, aligned = [], [], []
    for result in results:
        counts = dict(getattr(result.data, register).get_counts())
        if (sum(counts.values()) != shots or any(len(bits) != 1 or set(bits) - {"0", "1"}
                or type(value) is not int or value < 0 for bits, value in counts.items())):
            raise ValueError("Memory measurement histogram does not match the requested shots.")
        histograms.append(counts)
        fidelities.append(counts.get("0", 0) / shots)
        aligned.append(HardwareBackend._aligned_shots(result.data))
    return histograms, fidelities, aligned


def _memory_payload(config, counts, fidelities, metadata, *, backend, job_id=None, experiment_type="hardware"):
    return {"experiment_type": experiment_type, "experiment_kind": "memory", "backend": backend,
            "job_id": job_id, "shots": config["shots"], "seed": config["seed"],
            "optimization_level": config["optimization_level"], "use_qec": config["use_qec"],
            "state_prep": {"theta": config["theta"], "phi": config["phi"]},
            "tau_values": config["tau_values_dt"], "backend_counts": counts,
            "backend_fidelities": fidelities, "metadata": metadata}


def run_memory_reference(config, *, results_dir=None, sampler=None):
    """Run and save the noise-free Aer reference using the common memory schema."""
    from .provenance import software_provenance
    circuit, circuits, register = build_memory_circuits(config)
    if sampler is None:
        from qiskit_aer.primitives import SamplerV2
        sampler = SamplerV2(seed=config["seed"])
    results = list(sampler.run([(c,) for c in circuits], shots=config["shots"]).result())
    if len(results) != len(circuits):
        raise ValueError("Memory reference returned an incomplete delay grid.")
    counts, fidelities, aligned = _memory_measurements(results, register, config["shots"])
    payload = _memory_payload(config, counts, fidelities,
                              {"software": software_provenance(), "aligned_shots": aligned,
                               "execution": {"experiment_id": config["experiment_id"], "reference": "noise-free"}},
                              backend="aer_simulator", experiment_type="simulation")
    payload["ideal_fidelities"] = fidelities
    return save_memory_run(payload, results_dir=results_dir or DEFAULT_RESULTS_DIR)


def _prepare_memory(config, run_dir, *, service=None, results_dir=None):
    from qiskit.transpiler import generate_preset_pass_manager
    from .provenance import circuit_provenance, software_provenance
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    plan = _memory_plan(config)
    _durable_json({"config": config, "plan": plan}, run_dir / "plan.json")
    service = _service(config) if service is None else service
    backend = service.backend(config["backend"])
    target = backend.target
    dt = getattr(target, "dt", None)
    if dt is None or not math.isfinite(dt) or dt <= 0:
        raise ValueError("Backend must publish a positive dt before preparing this memory experiment.")
    step = math.lcm(getattr(target, "granularity", 1) or 1, getattr(target, "pulse_alignment", 1) or 1)
    if any(tau % step for tau in config["tau_values_dt"]):
        raise ValueError(f"Memory delays must be multiples of {step} dt; delays are never rounded.")
    circuit, bound, register = build_memory_circuits(config)
    if circuit.num_qubits > backend.num_qubits:
        raise ValueError("The memory circuit exceeds backend qubit capacity.")
    manager = generate_preset_pass_manager(backend=backend, optimization_level=config["optimization_level"],
                                           seed_transpiler=config["seed_transpiler"])
    # Bound circuits avoid symbolic-duration target/QPY incompatibilities.
    circuits = manager.run(bound)
    HardwareBackend._validate_target(circuits, backend)
    metadata = {"dt": dt, "software": software_provenance(),
                "input_circuit": circuit_provenance(circuit),
                "compiled_circuits": [circuit_provenance(c, target) for c in circuits],
                "calibration": calibration_provenance(backend, circuits)}
    prepared = {"schema_version": 2, "run_id": uuid.uuid4().hex, "prepared_at": _now(),
                "config": config, "plan": plan,
                "results_dir": str(Path(results_dir or DEFAULT_RESULTS_DIR).resolve()),
                "cases": [{"register_name": register, "metadata": metadata}],
                "review": {"dt_seconds": dt, "required_delay_step_dt": step,
                           "delay_seconds": [tau * dt for tau in config["tau_values_dt"]],
                           "circuit_depths": [c.depth() for c in circuits]}}
    _durable_json(prepared, run_dir / "prepared.json")
    _durable_json({"sha256": _digest(prepared)}, run_dir / "prepared.sha256.json")
    return prepared


def _save_memory_result(prepared, receipt, container, output):
    from copy import deepcopy
    from qiskit_ibm_runtime import RuntimeEncoder
    config = prepared["config"]
    results = list(container)
    ordered = [None] * len(results)
    for pub, result in zip(receipt["submitted_pub_order"], results):
        ordered[pub["canonical_index"]] = result
    counts, fidelities, aligned = _memory_measurements(ordered, prepared["cases"][0]["register_name"], config["shots"])
    metadata = deepcopy(prepared["cases"][0]["metadata"])
    metadata["aligned_shots"] = aligned
    metadata["execution"] = {**receipt, "collected_at": _now(), "experiment_id": config["experiment_id"],
                             "config_sha256": prepared["plan"]["config_sha256"], "case_id": "memory",
                             "sampler_result_metadata": json.loads(json.dumps(getattr(container, "metadata", None), cls=RuntimeEncoder))}
    payload = _memory_payload(config, counts, fidelities, metadata, backend=config["backend"], job_id=receipt["job_id"])
    payload["timestamp"] = receipt.get("submitted_at", receipt["attempted_at"])
    path = save_memory_run(payload, filepath=output)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def _validated_memory_result(path, prepared, receipt):
    config = prepared["config"]
    try:
        run = load_run(path)
        execution = run["metadata"]["execution"]
        expected = {"experiment_id": config["experiment_id"], "run_id": prepared["run_id"],
                    "repeat_index": receipt["repeat_index"], "job_id": receipt["job_id"],
                    "config_sha256": prepared["plan"]["config_sha256"]}
        if any(execution.get(key) != value for key, value in expected.items()):
            raise ValueError("memory execution identity differs")
        if (run["experiment_kind"] != "memory" or run["backend"] != config["backend"]
                or run["job_id"] != receipt["job_id"] or run["shots"] != config["shots"]
                or run["use_qec"] != config["use_qec"]
                or run["state_prep"] != {"theta": config["theta"], "phi": config["phi"]}
                or run["sweep"]["values"] != config["tau_values_dt"]):
            raise ValueError("memory state or delay grid differs")
        counts = run["counts"]
        if len(counts) != 1 or len(counts[0]) != len(config["tau_values_dt"]):
            raise ValueError("incomplete memory count grid")
        for histogram, fidelity in zip(counts[0], run["fidelities"]):
            if (sum(histogram.values()) != config["shots"] or any(len(bits) != 1 or set(bits) - {"0", "1"}
                    or type(value) is not int or value < 0 for bits, value in histogram.items())
                    or not math.isclose(fidelity[0], histogram.get("0", 0) / config["shots"], rel_tol=0, abs_tol=1e-12)):
                raise ValueError("memory counts or fidelity differs")
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"Saved result does not match its prepared experiment: {path} ({exc}).") from exc
    return True
