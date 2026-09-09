"""Prepare immutable hardware campaigns, submit once, and recover by job ID.

Planning and status are offline. Only prepare, submit, collect and attach-job
create a Runtime service. Each repeat is a separate job with seeded, interleaved
PUB order; templates and layout are reused exactly across repeats. Submitted
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
from .results import save_run, write_run_json


CONFIG_KEYS = {
    "schema_version", "campaign_id", "runtime_account", "backend", "shots",
    "repeats", "seed", "seed_transpiler", "optimization_level", "alpha",
    "theta_samples", "tau_values_dt", "cases",
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
    _keys(config, CONFIG_KEYS, "Campaign")
    if config["schema_version"] != 1:
        raise ValueError("Unsupported campaign schema_version.")
    if not isinstance(config["campaign_id"], str) or not IDENTIFIER.fullmatch(config["campaign_id"]):
        raise ValueError("campaign_id must be a short filename-safe identifier.")
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
    samples = config["theta_samples"]
    if not isinstance(samples, list) or not samples or any(not isinstance(row, list) or not row for row in samples):
        raise ValueError("theta_samples must be a nonempty list of angle lists.")
    for row in samples:
        for theta in row:
            _finite(theta, "theta")
    if len({tuple(row) for row in samples}) != len(samples):
        raise ValueError("theta_samples must not contain duplicate samples.")
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
        if any(len(row) != case["M"] for row in samples):
            raise ValueError("Every theta sample must have M entries for every case.")
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
    return config


def read_config(path: str | Path) -> dict:
    return validate_config(json.loads(Path(path).read_text()))


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def plan_campaign(config: dict) -> dict:
    """Seeded block randomization interleaves every case at each theta/delay."""
    validate_config(config)
    rng = random.Random(config["seed"])
    points = [(ti, di) for ti in range(len(config["theta_samples"]))
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
        repeats.append({"repeat_index": repeat, "pub_order": order})
    pubs = len(points) * len(config["cases"])
    return {"campaign_id": config["campaign_id"], "backend": config["backend"],
            "runtime_account": config["runtime_account"], "config_sha256": _digest(config),
            "jobs": config["repeats"], "pubs_per_job": pubs,
            "total_pubs": pubs * config["repeats"],
            "total_shots": pubs * config["repeats"] * config["shots"],
            "shots_per_pub": config["shots"], "order_note": ORDER_NOTE, "repeats": repeats}


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
    # campaign mutations hold this lock, including the brief submit/receipt gap.
    with (Path(run_dir) / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def prepare_campaign(config: dict, run_dir: str | Path, *, service=None) -> dict:
    """Freeze all compiled circuits and calibration before any submission."""
    validate_config(config, online=True)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    plan = plan_campaign(config)
    _durable_json({"config": config, "plan": plan}, run_dir / "plan.json")
    service = _service(config) if service is None else service
    backend = service.backend(config["backend"])
    dt = getattr(getattr(backend, "target", None), "dt", None)
    if dt is None or not math.isfinite(dt) or dt <= 0:
        raise ValueError("Backend must publish a positive dt before preparing this dt-based campaign.")
    cases = []
    shared_layouts = {}
    for case in config["cases"]:
        key = (case["M"], case["N"])
        if case["initial_layout"] is not None:
            if key in shared_layouts and shared_layouts[key] != case["initial_layout"]:
                raise ValueError("Matched M,N cases must use the same initial_layout.")
            shared_layouts[key] = case["initial_layout"]
    for case in config["cases"]:
        key = (case["M"], case["N"])
        hardware = HardwareBackend(
            service, config["backend"], shots=config["shots"],
            optimization_level=config["optimization_level"],
            seed_transpiler=config["seed_transpiler"], initial_layout=shared_layouts.get(key),
        )
        protocol = ProtocolConfig(M=case["M"], N=case["N"], alpha=config["alpha"],
                                  thetas=config["theta_samples"][0], use_qec=False)
        cases.append(hardware.prepare_tau_sweep(
            protocol, config["tau_values_dt"], theta_samples=config["theta_samples"],
            receiver_delay_factors=case["receiver_delay_factors"], backend=backend,
        ))
        shared_layouts[key] = cases[-1]["metadata"]["initial_layout"]
    mapping_review = []
    receiver_mappings = {}
    for case, compiled in zip(config["cases"], cases):
        for index, archived in enumerate(compiled["metadata"]["compiled_circuits"]):
            layout = archived["layout"]
            mapping = layout["final_index_layout"][-case["N"]:] if layout else None
            mapping_review.append({"case_id": case["id"], "canonical_index": index,
                                   "receiver_output_qubits": mapping})
            receiver_mappings.setdefault((case["M"], case["N"]), set()).add(tuple(mapping) if mapping else None)
    warnings = [f"M={m},N={n}: receiver output mappings differ between compiled conditions; inspect mapping_review before comparing controls."
                for (m, n), mappings in receiver_mappings.items() if len(mappings) > 1 or None in mappings]
    prepared = {"schema_version": 1, "run_id": uuid.uuid4().hex,
                "prepared_at": _now(), "config": config, "plan": plan, "cases": cases,
                "review": {"dt_seconds": dt,
                           "delay_seconds": [tau * dt for tau in config["tau_values_dt"]],
                           "shared_initial_layouts": {f"M{m}N{n}": layout for (m, n), layout in shared_layouts.items()},
                           "mapping_review": mapping_review, "comparison_warnings": warnings}}
    _durable_json(prepared, run_dir / "prepared.json")
    _durable_json({"sha256": _digest(prepared)}, run_dir / "prepared.sha256.json")
    return prepared


def _load_prepared(run_dir):
    run_dir = Path(run_dir)
    prepared = json.loads((run_dir / "prepared.json").read_text())
    checksum = json.loads((run_dir / "prepared.sha256.json").read_text())["sha256"]
    if _digest(prepared) != checksum or _digest(prepared["config"]) != prepared["plan"]["config_sha256"]:
        raise ValueError("Prepared campaign checksum mismatch; prepare a new directory for changes.")
    validate_config(prepared["config"], online=True)
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
        raise ValueError(f"Record does not match the prepared campaign: {path}.")
    return record


def campaign_status(run_dir: str | Path) -> dict:
    """Report durable local state without contacting IBM."""
    prepared = _load_prepared(run_dir)
    states = []
    for repeat in range(prepared["config"]["repeats"]):
        receipt = _receipt_path(run_dir, repeat)
        attempt = _attempt_path(run_dir, repeat)
        state = "unsubmitted"
        job_id = None
        if receipt.exists():
            _load_record(run_dir, prepared, repeat)
            job_id = _load_record(run_dir, prepared, repeat, receipt=True)["job_id"]
            count = sum((Path(run_dir) / "results" / f"repeat_{repeat:03d}_{case['id']}.json").exists()
                        for case in prepared["config"]["cases"])
            state = "collected" if count == len(prepared["cases"]) else "submitted"
        elif attempt.exists():
            _load_record(run_dir, prepared, repeat)
            state = "ambiguous: reconcile the attempt; submission will not retry"
        states.append({"repeat_index": repeat, "state": state, "job_id": job_id})
    return {"run_id": prepared["run_id"], "campaign_id": prepared["config"]["campaign_id"], "repeats": states}


def _ordered_circuits(prepared, order):
    circuits = [HardwareBackend.replay_prepared(case) for case in prepared["cases"]]
    return [circuits[pub["case_index"]][pub["canonical_index"]] for pub in order]


def submit_campaign(run_dir: str | Path, *, service=None, sampler_factory=None) -> list[str]:
    """Submit only never-attempted repeats; save each job ID before continuing."""
    with _locked(run_dir):
        prepared = _load_prepared(run_dir)
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
            circuits = _ordered_circuits(prepared, order)
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
        raise ValueError("Job backend does not match the prepared campaign.")
    from qiskit.primitives.containers.sampler_pub import SamplerPub
    inputs = job.inputs
    pubs = [SamplerPub.coerce(pub, shots=inputs.get("options", {}).get("default_shots"))
            for pub in inputs["pubs"]]
    if len(pubs) != len(circuits) or any(pub.circuit != circuit or pub.parameter_values.num_parameters
                                        for pub, circuit in zip(pubs, circuits)):
        raise ValueError("Job PUB circuits/order do not match the archived preparation.")
    if any(pub.shots != prepared["config"]["shots"] for pub in pubs):
        raise ValueError("Job shots do not match the campaign.")


def attach_job(run_dir, repeat: int, job_id: str, *, service=None):
    """Recover an interrupted submit by explicitly linking its matching job ID."""
    with _locked(run_dir):
        prepared = _load_prepared(run_dir)
        _integer(repeat, "repeat")
        if repeat >= prepared["config"]["repeats"]:
            raise ValueError("repeat index is outside this campaign.")
        if _receipt_path(run_dir, repeat).exists():
            raise FileExistsError("This repeat already has a receipt.")
        attempt = _load_record(run_dir, prepared, repeat)
        service = _service(prepared["config"]) if service is None else service
        job = service.job(job_id)
        order = prepared["plan"]["repeats"][repeat]["pub_order"]
        _verify_job(job, prepared, repeat, _ordered_circuits(prepared, order))
        return _durable_json({**attempt, "job_id": job_id, "recovered_at": _now(),
                              "submitted_pub_order": order, "actual_device_order_note": ORDER_NOTE},
                             _receipt_path(run_dir, repeat))


def collect_campaign(run_dir: str | Path, *, service=None) -> list[Path]:
    """Retrieve known jobs by ID, preserving each repeat and case separately."""
    with _locked(run_dir):
        prepared = _load_prepared(run_dir)
        config = prepared["config"]
        receipts = []
        for ri in range(config["repeats"]):
            if _receipt_path(run_dir, ri).exists():
                _load_record(run_dir, prepared, ri)
                receipts.append(_load_record(run_dir, prepared, ri, receipt=True))
        if not receipts:
            return []
        service = _service(config) if service is None else service
        paths = []
        for receipt in receipts:
            ri = receipt["repeat_index"]
            outputs = [Path(run_dir) / "results" / f"repeat_{ri:03d}_{case['id']}.json" for case in config["cases"]]
            if all(path.exists() for path in outputs):
                continue
            job = service.job(receipt["job_id"])
            order = receipt["submitted_pub_order"]
            _verify_job(job, prepared, ri, _ordered_circuits(prepared, order))
            container = job.result()
            results = list(container)
            if len(results) != len(order):
                raise ValueError("Job returned a different number of PUB results than submitted.")
            for ci, (case, output) in enumerate(zip(config["cases"], outputs)):
                if output.exists():
                    continue
                indices = sorted((index for index, pub in enumerate(order) if pub["case_index"] == ci),
                                 key=lambda index: order[index]["canonical_index"])
                result = HardwareBackend.collect_prepared(
                    prepared["cases"][ci], [results[index] for index in indices], job_id=receipt["job_id"],
                    execution={**receipt, "collected_at": _now()},
                )
                # Full-container metadata includes execution spans for all PUBs.
                from qiskit_ibm_runtime import RuntimeEncoder
                result.metadata["execution"]["sampler_result_metadata"] = json.loads(json.dumps(
                    getattr(container, "metadata", None), cls=RuntimeEncoder))
                result.metadata["campaign"] = {
                    "campaign_id": config["campaign_id"], "run_id": prepared["run_id"],
                    "repeat_index": ri, "case_id": case["id"],
                    "config_sha256": prepared["plan"]["config_sha256"],
                    "receiver_delay_factors": case["receiver_delay_factors"],
                    "submitted_pub_indices": indices,
                }
                path = save_run(result, ProtocolConfig(**prepared["cases"][ci]["config"]), filepath=output)
                descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                paths.append(path)
        return paths
