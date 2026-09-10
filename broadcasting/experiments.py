"""Durable hardware jobs stored as self-contained JSON files in results/.

One file owns each Runtime job's frozen circuits, submission attempt, receipt,
and measured cases. Atomic transitions prevent ambiguous jobs from being retried;
completed measurements are immutable. Planning and status are entirely offline.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import tempfile
import uuid

from .backend import HardwareBackend, _sampler_settings
from .protocol import ProtocolConfig
from .provenance import calibration_provenance
from .results import (make_run_record, make_memory_record, save_memory_run,
                      validate_run_record, write_run_json)

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
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


def _case_pub_indices(order, case_index):
    return sorted((index for index, pub in enumerate(order) if pub["case_index"] == case_index),
                  key=lambda index: order[index]["canonical_index"])


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


def _build_preparation(config: dict, *, service=None) -> dict:
    """Freeze all compiled circuits and calibration before any submission."""
    validate_config(config, online=True)
    if config.get("experiment_kind") == "memory":
        return _build_memory_preparation(config, service=service)
    plan = plan_experiment(config)
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
                "review": {"dt_seconds": dt, "required_delay_step_dt": delay_step,
                           "circuit_review": circuit_review,
                           "delay_seconds": [tau * dt for tau in config["tau_values_dt"]],
                           "shared_initial_layouts": {f"M{m}N{n}": layout for (m, n), layout in shared_layouts.items()},
                           "mapping_review": mapping_review, "comparison_warnings": warnings}}
    if config["schema_version"] == 2:
        prepared["repeat_case_indices"] = repeat_case_indices
    return prepared


def _build_memory_preparation(config, *, service=None):
    from qiskit.transpiler import generate_preset_pass_manager
    from .provenance import circuit_provenance, software_provenance
    plan = _memory_plan(config)
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
                "cases": [{"register_name": register, "metadata": metadata}],
                "review": {"dt_seconds": dt, "required_delay_step_dt": step,
                           "delay_seconds": [tau * dt for tau in config["tau_values_dt"]],
                           "circuit_depths": [c.depth() for c in circuits]}}
    return prepared


def _normal_config(config):
    config = deepcopy(config)
    if "campaign_id" in config:
        config["experiment_id"] = config.pop("campaign_id")
    return validate_config(config)


def execution_document(bundle, repeat, *, attempt=None, receipt=None, measurements=None,
                       source_preparation_sha256=None):
    """Extract one fully recoverable job from a frozen preparation bundle."""
    config = bundle["config"]
    if config.get("experiment_kind") == "memory":
        cases = [bundle["cases"][0]]
    else:
        indices = (bundle["repeat_case_indices"][repeat] if bundle["schema_version"] == 2
                   else range(len(config["cases"])))
        cases = [bundle["cases"][index] for index in indices]
    prepared = {"run_id": bundle["run_id"], "prepared_at": bundle["prepared_at"],
                "config": deepcopy(config), "config_sha256": bundle["plan"]["config_sha256"],
                "job_plan": deepcopy(bundle["plan"]["repeats"][repeat]),
                "cases": deepcopy(cases), "review": deepcopy(bundle.get("review", {}))}
    if source_preparation_sha256:
        prepared["source_preparation_sha256"] = source_preparation_sha256
    state = "collected" if measurements else "submitted" if receipt else "attempted" if attempt else "prepared"
    return {"schema_version": 3, "document_type": "execution",
            "experiment_kind": config.get("experiment_kind", "broadcasting"),
            "state": state, "repeat_index": repeat, "prepared": prepared,
            "prepared_sha256": _digest(prepared), "attempt": deepcopy(attempt),
            "receipt": deepcopy(receipt), "measurements": deepcopy(measurements or [])}


def _paths(paths):
    selected = [Path(paths)] if isinstance(paths, (str, Path)) else [Path(path) for path in paths]
    if len({path.resolve() for path in selected}) != len(selected):
        raise ValueError("Select each experiment JSON only once.")
    return selected


@contextmanager
def _locked(directory):
    # Lock the stable directory inode. Locking a JSON inode would not protect its
    # atomic replacement; this needs no persistent lock file or sidecar.
    descriptor = os.open(Path(directory), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def _store_directory(paths):
    parents = {path.resolve().parent for path in paths}
    if len(parents) != 1:
        raise ValueError("Selected job JSON files must share one results directory.")
    return parents.pop()


def _write_state(document, path, *, create=False):
    """Fsync a full JSON and publish atomically; completed files never change."""
    path = Path(path)
    if create:
        output = write_run_json(document, path)
    else:
        previous = json.loads(path.read_text())
        allowed = {"prepared": "attempted", "attempted": "submitted", "submitted": "collected"}
        if previous["state"] == "collected" or allowed.get(previous["state"]) != document["state"]:
            raise ValueError("Invalid execution transition; collected measurements cannot be overwritten.")
        if previous["prepared_sha256"] != document["prepared_sha256"]:
            raise ValueError("Frozen preparation changed during execution.")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".execution-", suffix=".json", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(document, handle, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            output = path
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return output


def _tags(document):
    return [f"broadcast-{document['prepared']['run_id']}", f"repeat-{document['repeat_index']:03d}"]


def _validate_submission_record(document, record, *, receipt=False):
    prepared = document["prepared"]
    order = prepared["job_plan"]["pub_order"]
    expected = {"run_id": prepared["run_id"], "repeat_index": document["repeat_index"],
                "shots": prepared["config"]["shots"], "job_tags": _tags(document),
                "intended_pub_order": order}
    if receipt:
        expected["submitted_pub_order"] = order
        if not isinstance(record.get("job_id"), str) or not record["job_id"].strip():
            raise ValueError("Invalid job ID in execution receipt.")
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError("Submission record does not match the frozen experiment.")


def load_experiment(path, *, expected_config=None):
    """Validate one self-contained execution JSON entirely offline."""
    document = json.loads(Path(path).read_text())
    if document.get("schema_version") != 3 or document.get("document_type") != "execution":
        raise ValueError("Expected a self-contained execution JSON.")
    prepared = document["prepared"]
    if _digest(prepared) != document["prepared_sha256"] or _digest(prepared["config"]) != prepared["config_sha256"]:
        raise ValueError("Prepared experiment checksum mismatch.")
    config = _normal_config(prepared["config"])
    if expected_config is not None and config != validate_config(expected_config):
        raise ValueError("Notebook/config differs from this frozen preparation. Select a matching job or use a new experiment_id.")
    if (type(document["repeat_index"]) is not int or not 0 <= document["repeat_index"] < config["repeats"]
            or prepared["job_plan"]["repeat_index"] != document["repeat_index"]
            or len(prepared["cases"]) != len(config["cases"])):
        raise ValueError("Invalid repeat or prepared case mapping.")
    state = document["state"]
    if state not in {"prepared", "attempted", "submitted", "collected"}:
        raise ValueError("Unknown experiment state.")
    if state != "prepared":
        _validate_submission_record(document, document["attempt"])
    elif document.get("attempt") is not None:
        raise ValueError("Prepared state contains a submission attempt.")
    if state in {"submitted", "collected"}:
        _validate_submission_record(document, document["receipt"], receipt=True)
    elif document.get("receipt") is not None:
        raise ValueError("Unsubmitted state contains a receipt.")
    if state == "collected":
        _validate_measurements(document)
    elif document.get("measurements"):
        raise ValueError("Incomplete execution contains published measurements.")
    return document


def find_experiments(config=None, *, results_dir=None):
    """Find saved job JSONs, optionally matching every frozen configuration field."""
    result = []
    for path in sorted(Path(results_dir or DEFAULT_RESULTS_DIR).glob("job_*.json")):
        document = load_experiment(path)
        if config is None or _normal_config(document["prepared"]["config"]) == validate_config(config):
            result.append(path)
    return result


def prepare_experiment(config, *, results_dir=None, service=None):
    """Freeze all cases, then save one prepared JSON per repeat without submitting."""
    validate_config(config, online=True)
    bundle = _build_preparation(config, service=service)
    directory = Path(results_dir or DEFAULT_RESULTS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    with _locked(directory):
        for repeat in range(config["repeats"]):
            document = execution_document(bundle, repeat)
            path = directory / f"job_{bundle['run_id']}_repeat_{repeat:03d}.json"
            paths.append(_write_state(document, path, create=True))
    return paths


def experiment_status(paths):
    """Report state without account access or creating any files."""
    jobs = []
    for path in _paths(paths):
        document = load_experiment(path)
        jobs.append({"path": str(path), "experiment_id": _normal_config(document["prepared"]["config"])["experiment_id"],
                     "repeat_index": document["repeat_index"], "state": document["state"],
                     "job_id": (document["receipt"] or {}).get("job_id"),
                     "measurements": len(document["measurements"])})
    return {"jobs": jobs}


def _ordered_circuits(document):
    cases = [HardwareBackend.replay_prepared(case) for case in document["prepared"]["cases"]]
    return [cases[pub["case_index"]][pub["canonical_index"]]
            for pub in document["prepared"]["job_plan"]["pub_order"]]


def _verify_job(job, document):
    """Check recovered identity, exact circuits, ordering, and shots before linking."""
    config = _normal_config(document["prepared"]["config"])
    if not set(_tags(document)).issubset(set(job.tags)):
        raise ValueError("Job tags do not match this run and repeat.")
    if job.backend().name != config["backend"]:
        raise ValueError("Job backend does not match the prepared experiment.")
    from qiskit.primitives.containers.sampler_pub import SamplerPub
    inputs = job.inputs
    pubs = [SamplerPub.coerce(pub, shots=inputs.get("options", {}).get("default_shots")) for pub in inputs["pubs"]]
    circuits = _ordered_circuits(document)
    if len(pubs) != len(circuits) or any(pub.circuit != circuit or pub.parameter_values.num_parameters
                                       for pub, circuit in zip(pubs, circuits)):
        raise ValueError("Job PUB circuits/order do not match the archived preparation.")
    if any(pub.shots != config["shots"] for pub in pubs):
        raise ValueError("Job shots do not match the experiment.")


def submit_experiment(paths, *, service=None, sampler_factory=None):
    """Submit only prepared jobs; persist attempted state before every API call."""
    paths = _paths(paths)
    if not paths:
        return []
    submitted = []
    services = {}
    with _locked(_store_directory(paths)):
        documents = [(path, load_experiment(path)) for path in paths]
        if any(document["state"] == "attempted" for _, document in documents):
            raise ValueError("Ambiguous submission: identify its tagged job and use attach-job; submission will not retry.")
        for path, document in documents:
            if document["state"] != "prepared":
                continue
            config = _normal_config(document["prepared"]["config"])
            if service is None and config["runtime_account"] not in services:
                services[config["runtime_account"]] = _service(config)
            current_service = service or services[config["runtime_account"]]
            backend = current_service.backend(config["backend"])
            if getattr(getattr(backend, "target", None), "dt", None) != document["prepared"]["cases"][0]["metadata"]["dt"]:
                raise ValueError("Backend dt changed since preparation; prepare a new experiment.")
            circuits = _ordered_circuits(document)
            HardwareBackend._validate_target(circuits, backend)
            if sampler_factory is None:
                from qiskit_ibm_runtime import SamplerV2
                sampler = SamplerV2(mode=backend, options={"environment": {"job_tags": _tags(document)}})
            else:
                sampler = sampler_factory(backend, _tags(document))
            attempt = {"run_id": document["prepared"]["run_id"], "repeat_index": document["repeat_index"],
                       "attempted_at": _now(), "job_tags": _tags(document),
                       "intended_pub_order": document["prepared"]["job_plan"]["pub_order"],
                       "shots": config["shots"], "sampler_options": _sampler_settings(sampler),
                       "submission_calibration": calibration_provenance(backend, circuits)}
            document.update(state="attempted", attempt=attempt)
            _write_state(document, path)
            job = sampler.run([(circuit,) for circuit in circuits], shots=config["shots"])
            receipt = {**attempt, "job_id": job.job_id(), "submitted_at": _now(),
                       "submitted_pub_order": attempt["intended_pub_order"], "actual_device_order_note": ORDER_NOTE}
            _validate_submission_record(document, receipt, receipt=True)
            document.update(state="submitted", receipt=receipt)
            _write_state(document, path)
            submitted.append(receipt["job_id"])
            print(f"Repeat {document['repeat_index']}: saved job ID {receipt['job_id']}", flush=True)
    return submitted


def attach_job(path, job_id, *, service=None):
    """Link the matching accepted job after an interrupted submission."""
    path = Path(path)
    with _locked(path.parent):
        document = load_experiment(path)
        if document["state"] != "attempted":
            raise ValueError("Only an ambiguous submission attempt can be attached.")
        config = _normal_config(document["prepared"]["config"])
        service = _service(config) if service is None else service
        job = service.job(job_id)
        _verify_job(job, document)
        document.update(state="submitted", receipt={**document["attempt"], "job_id": job_id,
                         "recovered_at": _now(), "submitted_pub_order": document["prepared"]["job_plan"]["pub_order"],
                         "actual_device_order_note": ORDER_NOTE})
        return _write_state(document, path)


def _case_measurements(document, container):
    from qiskit_ibm_runtime import RuntimeEncoder
    prepared, receipt = document["prepared"], document["receipt"]
    config = _normal_config(prepared["config"])
    results = list(container)
    order = prepared["job_plan"]["pub_order"]
    if len(results) != len(order):
        raise ValueError("Job returned a different number of PUB results than submitted.")
    measured = []
    for ci, (case, compiled) in enumerate(zip(config["cases"], prepared["cases"])):
        indices = _case_pub_indices(order, ci)
        execution = {**receipt, "collected_at": _now(), "experiment_id": config["experiment_id"],
                     "case_id": case["id"], "case_index": ci, "config_sha256": prepared["config_sha256"],
                     "submitted_pub_indices": indices,
                     "sampler_result_metadata": json.loads(json.dumps(getattr(container, "metadata", None), cls=RuntimeEncoder))}
        if config.get("experiment_kind") == "memory":
            counts, fidelities, aligned = _memory_measurements([results[index] for index in indices],
                                                               compiled["register_name"], config["shots"])
            metadata = deepcopy(compiled["metadata"])
            metadata.update(aligned_shots=aligned, execution=execution)
            payload = _memory_payload(config, counts, fidelities, metadata, backend=config["backend"], job_id=receipt["job_id"])
            payload["timestamp"] = receipt.get("submitted_at", receipt["attempted_at"])
            measured.append(make_memory_record(payload))
        else:
            execution.update(receiver_delay_factors=case["receiver_delay_factors"],
                             phase_design=config.get("phase_design", {"kind": "fixed"}),
                             phase_seed=config.get("phase_design", {}).get("seed"),
                             theta_samples=compiled["metadata"]["theta_samples"])
            result = HardwareBackend.collect_prepared(compiled, [results[index] for index in indices],
                                                      job_id=receipt["job_id"], execution=execution)
            measured.append(make_run_record(result, ProtocolConfig(**compiled["config"])))
    return measured


def _validate_measurements(document):
    prepared, receipt = document["prepared"], document["receipt"]
    config = _normal_config(prepared["config"])
    measurements = document["measurements"]
    if len(measurements) != len(config["cases"]):
        raise ValueError("Collected job has an incomplete measured-case grid.")
    ids = [run.get("record_id") for run in measurements]
    if len(set(ids)) != len(ids):
        raise ValueError("Measured case record IDs are not unique.")
    for ci, (run, case, compiled) in enumerate(zip(measurements, config["cases"], prepared["cases"])):
        validate_run_record(run)
        execution = run["metadata"]["execution"]
        expected = {"experiment_id": config["experiment_id"], "run_id": prepared["run_id"],
                    "repeat_index": document["repeat_index"], "case_id": case["id"],
                    "config_sha256": prepared["config_sha256"], "job_id": receipt["job_id"],
                    "submitted_pub_indices": _case_pub_indices(prepared["job_plan"]["pub_order"], ci)}
        if any(execution.get(key) != value for key, value in expected.items()):
            raise ValueError("Saved measurement does not match the execution identity.")
        if (run["experiment_kind"] != document["experiment_kind"] or run["experiment_type"] != "hardware" or run["backend"] != config["backend"]
                or run["job_id"] != receipt["job_id"] or run["shots"] != config["shots"]
                or run["optimization_level"] != config["optimization_level"]
                or run["sweep"]["axis"] != "tau" or run["sweep"]["values"] != config["tau_values_dt"]):
            raise ValueError("Saved measurement does not match its prepared hardware settings.")
        if config.get("experiment_kind") == "memory":
            expected_protocol = {"M": 0, "N": 1, "use_qec": config["use_qec"],
                                 "state_prep": {"theta": config["theta"], "phi": config["phi"]}}
            samples = [[config["theta"], config["phi"]]]
        else:
            samples = compiled["metadata"]["theta_samples"]
            expected_protocol = {"M": case["M"], "N": case["N"], "alpha": config["alpha"], "use_qec": False,
                                 "theta_samples": samples}
            if execution.get("receiver_delay_factors") != case["receiver_delay_factors"]:
                raise ValueError("Saved measurement uses different receiver delay factors.")
        if any(run["protocol"].get(key) != value for key, value in expected_protocol.items()):
            raise ValueError("Saved measurement has different state preparation or protocol.")
        counts = run["counts"]
        if len(counts) != len(samples) or any(len(row) != len(config["tau_values_dt"]) for row in counts):
            raise ValueError("Saved measurement has an incomplete count grid.")
        receivers = run["protocol"]["N"]
        for di, values in enumerate(run["fidelities"]):
            local = []
            for row in counts:
                histogram = row[di]
                if sum(histogram.values()) != config["shots"]:
                    raise ValueError("Saved measurement shot count differs from the receipt.")
                local.append(HardwareBackend._fidelities_from_counts(histogram, receivers))
            if any(not math.isclose(value, sum(row[receiver] for row in local) / len(samples),
                                    rel_tol=0, abs_tol=1e-12) for receiver, value in enumerate(values)):
                raise ValueError("Saved fidelities disagree with the saved counts.")


def collect_experiment(paths, *, service=None):
    """Finalize each submitted job atomically, retaining all measured cases inside it."""
    paths = _paths(paths)
    if not paths:
        return []
    updated, services = [], {}
    with _locked(_store_directory(paths)):
        documents = [(path, load_experiment(path)) for path in paths]
        for path, document in documents:
            if document["state"] != "submitted":
                continue
            config = _normal_config(document["prepared"]["config"])
            if service is None and config["runtime_account"] not in services:
                services[config["runtime_account"]] = _service(config)
            current_service = service or services[config["runtime_account"]]
            job = current_service.job(document["receipt"]["job_id"])
            _verify_job(job, document)
            measurements = _case_measurements(document, job.result())
            document.update(state="collected", measurements=measurements)
            _validate_measurements(document)
            updated.append(_write_state(document, path))
    return updated
