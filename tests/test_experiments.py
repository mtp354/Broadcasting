"""Offline durable state transitions and measured-case preservation in flat job JSONs."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from qiskit.primitives.containers import BitArray, DataBin, PrimitiveResult, SamplerPubResult
from qiskit_aer import AerSimulator

from broadcasting.backend import HardwareBackend
from broadcasting.experiments import (
    attach_job, collect_experiment, execution_document, experiment_status,
    find_experiments, load_experiment, make_experiment_config, make_memory_config,
    plan_experiment, prepare_experiment, run_memory_reference, submit_experiment,
    validate_config, _build_preparation, _digest, _locked, _write_state,
)
from broadcasting.results import load_run, list_runs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_results(tmp_path, monkeypatch):
    monkeypatch.setattr("broadcasting.experiments.DEFAULT_RESULTS_DIR", tmp_path / "results")


@pytest.fixture
def config():
    data = make_experiment_config("delay", runtime_account="offline-test", backend="aer_simulator")
    data.pop("phase_design")
    data.update(schema_version=1, shots=16, repeats=2, optimization_level=0,
                theta_samples=[[0.3], [0.8]], tau_values_dt=[0, 768])
    data["cases"] = [
        {"id": "uniform", "M": 1, "N": 2, "receiver_delay_factors": [1, 1], "initial_layout": None},
        {"id": "receiver0", "M": 1, "N": 2, "receiver_delay_factors": [1, 0], "initial_layout": None},
    ]
    return data



class OfflineJob:
    def __init__(self, name, backend, tags, pubs, shots):
        self.name = name
        self._backend = backend
        self.tags = tags
        from qiskit_ibm_runtime import RuntimeDecoder, RuntimeEncoder
        from qiskit.primitives.containers.sampler_pub import SamplerPub
        self.inputs = json.loads(json.dumps(
            {"pubs": [SamplerPub.coerce((pub[0], None, shots)) for pub in pubs]},
            cls=RuntimeEncoder), cls=RuntimeDecoder)
        self.fail_result = False
        rows = []
        for index, pub in enumerate(pubs):
            registers = {}
            for register in pub[0].cregs:
                # Position-dependent counts detect incorrect de-interleaving.
                zeroes = max(1, shots - index)
                registers[register.name] = BitArray.from_samples(
                    ["0" * register.size] * zeroes + ["1" * register.size] * (shots - zeroes),
                    num_bits=register.size)
            rows.append(SamplerPubResult(DataBin(**registers), metadata={"pub_index": index}))
        self.container = PrimitiveResult(rows, metadata={"execution": {"offline": True}})

    def job_id(self):
        return self.name

    def backend(self):
        return self._backend

    def result(self):
        if self.fail_result:
            raise RuntimeError("Temporary retrieval failure")
        return self.container


class OfflineService:
    def __init__(self):
        class TimedAer(AerSimulator):
            @property
            def target(self):
                target = super().target
                target.dt = 1e-9
                return target
        self.target = TimedAer()
        self.jobs = {}
        self.calls = 0
        self.fail_after_submit = False

    def backend(self, name):
        assert name == self.target.name
        return self.target

    def job(self, job_id):
        return self.jobs[job_id]

    def sampler(self, backend, tags):
        def run(pubs, shots):
            self.calls += 1
            job = OfflineJob(f"job-{self.calls}", backend, tags, pubs, shots)
            self.jobs[job.name] = job
            if self.fail_after_submit:
                raise RuntimeError("Connection lost after accepted job")
            return job
        return SimpleNamespace(run=run)


@pytest.mark.parametrize("key,value", [
    ("shots", 0), ("shots", True), ("repeats", -1), ("seed", 1.5),
    ("alpha", float("nan")), ("alpha", 2), ("alpha", "0.5"),
    ("theta_samples", [[True]]), ("theta_samples", [[0.1], [0.1]]),
    ("theta_samples", [[0.1, 0.2]]), ("tau_values_dt", [0, 0]),
    ("tau_values_dt", [-1]), ("tau_values_dt", [0.5]),
    ("optimization_level", 4), ("backend", ""),
])
def test_invalid_configs_fail_before_any_lookup(tmp_path, config, monkeypatch, key, value):
    config[key] = value
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Network lookup"))
    with pytest.raises(ValueError):
        prepare_experiment(config, results_dir=tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("changes", [
    {"id": "../bad"}, {"receiver_delay_factors": [0, 0]},
    {"receiver_delay_factors": [True, 1]}, {"initial_layout": [0, 1, 1, 2]},
    {"initial_layout": [0]}, {"unknown": 3},
])
def test_invalid_cases(config, changes):
    config["cases"][0].update(changes)
    with pytest.raises(ValueError):
        validate_config(config)


def test_automatic_and_explicit_layout_do_not_hide_duplicate_conditions(config):
    duplicate = deepcopy(config["cases"][0])
    duplicate.update(id="duplicate", initial_layout=[0, 1, 2, 3])
    config["cases"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate case"):
        validate_config(config)


def test_random_phase_plan_is_reproducible_and_pairs_sender_prefixes():
    config = make_experiment_config("scaling")
    plan = plan_experiment(config)
    assert plan == plan_experiment(deepcopy(config))
    phase_rows = []
    for repeat in plan["repeats"]:
        samples = repeat["phases"]["theta_samples_by_case"]
        largest = samples[-1][0]
        for case, rows in zip(config["cases"], samples):
            assert rows == [largest[:case["M"]]]
        for pub in repeat["pub_order"]:
            assert pub["thetas"] == samples[pub["case_index"]][pub["theta_index"]]
        phase_rows.append(tuple(largest))
    assert len(set(phase_rows)) == config["repeats"]
    assert plan["cases"][-1]["logical_qubits"] == 13
    changed_order = deepcopy(config)
    changed_order["seed"] += 1
    assert [row["phases"] for row in plan_experiment(changed_order)["repeats"]] == [row["phases"] for row in plan["repeats"]]
    assert plan_experiment(changed_order)["repeats"] != plan["repeats"]


@pytest.mark.parametrize("design", [
    {"kind": "unknown"},
    {"kind": "seeded_random", "seed": True, "samples_per_repeat": 1, "low": 0, "high": 6},
    {"kind": "seeded_random", "seed": 4, "samples_per_repeat": 0, "low": 0, "high": 6},
    {"kind": "seeded_random", "seed": 4, "samples_per_repeat": 1, "low": 1, "high": 1},
    {"kind": "fixed", "samples_by_m": {"1": [[0.1]]}},
    {"kind": "fixed", "samples_by_m": {"1": [[0.1]], "2": [[0.1, 0.2]], "3": [[0.1]]}},
])
def test_invalid_v2_phases_rejected_without_network(design):
    config = make_experiment_config("scaling")
    config["phase_design"] = design
    with pytest.raises(ValueError):
        plan_experiment(config)


@pytest.fixture
def prepared(config):
    service = OfflineService()
    paths = prepare_experiment(config, service=service)
    return paths, service



@pytest.mark.parametrize("kind,pubs,shots", [("delay", 363, 3630000), ("scaling", 36, 294912)])
def test_inline_defaults_preserve_budget_and_interleaving(kind, pubs, shots):
    config = make_experiment_config(kind)
    plan = plan_experiment(config)
    assert (plan["total_pubs"], plan["total_shots"]) == (pubs, shots)
    assert plan == plan_experiment(deepcopy(config))
    for repeat in plan["repeats"]:
        order = repeat["pub_order"]
        for index in range(0, len(order), len(config["cases"])):
            group = order[index:index + len(config["cases"])]
            assert len({(row["theta_index"], row["tau_index"]) for row in group}) == 1
            assert len({row["case_id"] for row in group}) == len(config["cases"])


def test_preparation_is_self_contained_and_replays_frozen_qpy(prepared, tmp_path):
    paths, service = prepared
    assert len(paths) == 2 and service.calls == 0
    assert set((tmp_path / "results").iterdir()) == set(paths)
    for path in paths:
        document = load_experiment(path)
        assert document["state"] == "prepared" and document["measurements"] == []
        assert document["attempt"] is document["receipt"] is None
        assert document["prepared"]["review"]["delay_seconds"] == pytest.approx([0, 768e-9])
        for case in document["prepared"]["cases"]:
            first = HardwareBackend.replay_prepared(case)
            second = HardwareBackend.replay_prepared(json.loads(json.dumps(case)))
            assert first == second and all(not circuit.parameters for circuit in first)
    assert find_experiments(load_experiment(paths[0])["prepared"]["config"]) == paths


def test_attempt_is_durable_before_submit_and_completed_jobs_are_immutable(prepared, monkeypatch):
    paths, service = prepared
    original_factory = service.sampler
    def sampler(backend, tags):
        delegate = original_factory(backend, tags)
        def run(pubs, shots):
            pending = next(path for path in paths if tags[1] == f"repeat-{load_experiment(path)['repeat_index']:03d}")
            record = load_experiment(pending)
            assert record["state"] == "attempted" and record["receipt"] is None
            return delegate.run(pubs, shots)
        return SimpleNamespace(run=run)
    assert submit_experiment(paths, service=service, sampler_factory=sampler) == ["job-1", "job-2"]
    assert submit_experiment(paths, service=service, sampler_factory=sampler) == []
    assert collect_experiment(paths, service=service) == paths
    assert all(job["state"] == "collected" and job["measurements"] == 2 for job in experiment_status(paths)["jobs"])
    originals = {path: path.read_bytes() for path in paths}
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Collected job accessed account"))
    monkeypatch.setattr("broadcasting.experiments._ordered_circuits", lambda _: pytest.fail("Collected job replayed circuits"))
    assert submit_experiment(paths) == collect_experiment(paths) == []
    assert all(path.read_bytes() == data for path, data in originals.items())
    with pytest.raises(ValueError, match="cannot be overwritten"):
        _write_state(load_experiment(paths[0]), paths[0])


def test_collection_keeps_each_case_theta_delay_and_receiver(prepared):
    paths, service = prepared
    submit_experiment(paths, service=service, sampler_factory=service.sampler)
    service.jobs["job-1"].fail_result = True
    before = [path.read_bytes() for path in paths]
    with pytest.raises(RuntimeError, match="retrieval"):
        collect_experiment(paths, service=service)
    assert [path.read_bytes() for path in paths] == before
    service.jobs["job-1"].fail_result = False
    collect_experiment(paths, service=service)
    for path in paths:
        document = load_experiment(path)
        for ci, run in enumerate(document["measurements"]):
            for ti, row in enumerate(run["counts"]):
                for di, counts in enumerate(row):
                    position = next(index for index, pub in enumerate(document["prepared"]["job_plan"]["pub_order"])
                                    if pub["case_index"] == ci and pub["theta_index"] == ti and pub["tau_index"] == di)
                    assert counts["00"] == max(1, 16 - position)
            assert run["metadata"]["execution"]["case_index"] == ci
            np.testing.assert_allclose(run["fidelities"], np.mean(run["per_theta_fidelities"], axis=0))


def test_ambiguous_attempt_never_resubmits_and_can_attach_exact_job(prepared):
    paths, service = prepared
    service.fail_after_submit = True
    with pytest.raises(RuntimeError, match="Connection lost"):
        submit_experiment(paths, service=service, sampler_factory=service.sampler)
    assert load_experiment(paths[0])["state"] == "attempted"
    with pytest.raises(ValueError, match="Ambiguous"):
        submit_experiment(paths, service=service, sampler_factory=service.sampler)
    job = service.jobs["job-1"]
    original_tags = job.tags
    job.tags = ["wrong"]
    with pytest.raises(ValueError, match="tags"):
        attach_job(paths[0], job.name, service=service)
    job.tags = original_tags
    original = job.inputs["pubs"][0]
    job.inputs["pubs"][0] = (original[0], None, 999)
    with pytest.raises(ValueError, match="shots"):
        attach_job(paths[0], job.name, service=service)
    modified = original[0].copy()
    modified.x(0)
    job.inputs["pubs"][0] = (modified, None, original[2])
    with pytest.raises(ValueError, match="circuits/order"):
        attach_job(paths[0], job.name, service=service)
    job.inputs["pubs"][0] = original
    attach_job(paths[0], job.name, service=service)
    service.fail_after_submit = False
    assert submit_experiment(paths, service=service, sampler_factory=service.sampler) == ["job-2"]
    assert collect_experiment(paths, service=service) == paths
    assert service.calls == 2


def test_receipt_publish_failure_leaves_recoverable_attempt(prepared, monkeypatch):
    paths, service = prepared
    original = os.replace
    def interrupted(source, destination):
        if json.loads(Path(source).read_text())["state"] == "submitted":
            raise OSError("receipt publication interrupted")
        return original(source, destination)
    monkeypatch.setattr("broadcasting.experiments.os.replace", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        submit_experiment(paths, service=service, sampler_factory=service.sampler)
    assert load_experiment(paths[0])["state"] == "attempted"
    assert not list(paths[0].parent.glob(".execution-*"))
    with pytest.raises(ValueError, match="Ambiguous"):
        submit_experiment(paths, service=service, sampler_factory=service.sampler)
    monkeypatch.setattr("broadcasting.experiments.os.replace", original)
    attach_job(paths[0], "job-1", service=service)
    assert service.calls == 1


def test_changed_dt_and_concurrent_submit_never_create_attempt(prepared):
    paths, service = prepared
    original = service.backend
    service.backend = lambda _: AerSimulator()
    with pytest.raises(ValueError, match="dt changed"):
        submit_experiment(paths, service=service, sampler_factory=service.sampler)
    service.backend = original
    with _locked(paths[0].parent):
        with pytest.raises(BlockingIOError):
            submit_experiment(paths, service=service, sampler_factory=service.sampler)
    assert service.calls == 0
    assert all(load_experiment(path)["state"] == "prepared" for path in paths)


@pytest.mark.parametrize("field,value", [("run_id", "wrong"), ("repeat_index", 999), ("shots", 999), ("submitted_pub_order", [])])
def test_edited_receipts_are_rejected_before_account_lookup(prepared, monkeypatch, field, value):
    paths, service = prepared
    submit_experiment(paths, service=service, sampler_factory=service.sampler)
    document = json.loads(paths[0].read_text())
    document["receipt"][field] = value
    paths[0].write_text(json.dumps(document))
    before = paths[0].read_bytes()
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Corrupt receipt accessed account"))
    for action in (experiment_status, submit_experiment, collect_experiment):
        with pytest.raises(ValueError, match="record does not match"):
            action(paths)
    assert paths[0].read_bytes() == before


def test_changed_preparation_or_notebook_settings_are_rejected(prepared, monkeypatch):
    paths, service = prepared
    config = deepcopy(load_experiment(paths[0])["prepared"]["config"])
    config["shots"] += 1
    with pytest.raises(ValueError, match="Notebook/config differs"):
        load_experiment(paths[0], expected_config=config)
    document = json.loads(paths[0].read_text())
    document["prepared"]["config"]["shots"] += 1
    paths[0].write_text(json.dumps(document))
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Corrupt preparation accessed account"))
    with pytest.raises(ValueError, match="checksum"):
        submit_experiment(paths)
    assert service.calls == 0


def test_incomplete_counts_cannot_partially_finalize_job(prepared):
    paths, service = prepared
    submit_experiment(paths, service=service, sampler_factory=service.sampler)
    rows = list(service.jobs["job-1"].container)
    rows[-1] = SamplerPubResult(DataBin(fid=BitArray.from_samples(["00"], num_bits=2)))
    service.jobs["job-1"].container = PrimitiveResult(rows)
    before = paths[0].read_bytes()
    with pytest.raises(ValueError, match="requested shots"):
        collect_experiment(paths, service=service)
    assert paths[0].read_bytes() == before
    assert load_experiment(paths[0])["measurements"] == []


@pytest.mark.parametrize("damage", ["counts", "fidelity", "case_id", "source_hash"])
def test_corrupt_completed_measurements_are_never_rewritten(prepared, monkeypatch, damage):
    paths, service = prepared
    submit_experiment(paths, service=service, sampler_factory=service.sampler)
    collect_experiment(paths, service=service)
    document = json.loads(paths[0].read_text())
    run = document["measurements"][0]
    if damage == "counts":
        run["counts"][0][0]["00"] -= 1
    elif damage == "fidelity":
        run["fidelities"][0][0] = 0.1
    elif damage == "case_id":
        run["metadata"]["execution"]["case_id"] = "wrong"
    else:
        run["metadata"]["execution"]["config_sha256"] = "wrong"
    paths[0].write_text(json.dumps(document))
    before = paths[0].read_bytes()
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Corrupt completion accessed account"))
    for action in (experiment_status, submit_experiment, collect_experiment):
        with pytest.raises(ValueError):
            action(paths)
    assert paths[0].read_bytes() == before


def test_random_mixed_sender_jobs_keep_their_own_phases(tmp_path):
    config = make_experiment_config("scaling", backend="aer_simulator", runtime_account="offline-test",
                                    sender_counts=[1, 2], receiver_counts=[1], repeats=2)
    config.update(shots=16, optimization_level=0)
    service = OfflineService()
    paths = prepare_experiment(config, results_dir=tmp_path / "results", service=service)
    submit_experiment(paths, service=service, sampler_factory=service.sampler)
    collect_experiment(paths, service=service)
    all_phases = []
    for path in paths:
        document = load_experiment(path)
        phases = document["prepared"]["job_plan"]["phases"]["theta_samples_by_case"]
        all_phases.append(phases)
        for run, expected in zip(document["measurements"], phases):
            assert run["protocol"]["theta_samples"] == expected
    assert all_phases[0] != all_phases[1]


@pytest.mark.parametrize("use_qec", [False, True])
def test_memory_uses_same_self_contained_job_lifecycle(tmp_path, use_qec):
    config = make_memory_config(runtime_account="offline-test", backend="aer_simulator", use_qec=use_qec,
                                theta=0.4, phi=0.8, tau_values_dt=[0, 768], shots=16, repeats=2)
    service = OfflineService()
    paths = prepare_experiment(config, results_dir=tmp_path / "results", service=service)
    submit_experiment(paths, service=service, sampler_factory=service.sampler)
    collect_experiment(paths, service=service)
    for path in paths:
        document = load_experiment(path)
        run, = document["measurements"]
        assert run["experiment_kind"] == "memory" and run["protocol"]["use_qec"] is use_qec
        assert run["protocol"]["state_prep"] == {"theta": 0.4, "phi": 0.8}
        for position, pub in enumerate(document["prepared"]["job_plan"]["pub_order"]):
            assert run["fidelities"][pub["canonical_index"]] == [(16 - position) / 16]
    assert collect_experiment(paths, service=service) == []


def test_memory_reference_saves_flat_canonical_measurement(tmp_path):
    config = make_memory_config(use_qec=True, tau_values_dt=[0, 100], shots=32)
    path = run_memory_reference(config, results_dir=tmp_path / "results")
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == 2 and raw["experiment_kind"] == "memory"
    assert raw["fidelities"] == [[1.0], [1.0]]
    assert raw["counts"] == [[{"0": 32}, {"0": 32}]]
    assert list(path.parent.iterdir()) == [path]


def test_extracted_job_keeps_original_configuration_hash_and_recovery(config, tmp_path):
    service = OfflineService()
    expected_config = deepcopy(config)
    bundle = _build_preparation(config, service=service)
    bundle["config"]["campaign_id"] = bundle["config"].pop("experiment_id")
    bundle["plan"]["config_sha256"] = _digest(bundle["config"])
    original_digest = _digest(bundle)
    document = execution_document(bundle, 0, source_preparation_sha256=original_digest)
    path = tmp_path / "job_test.json"
    _write_state(document, path, create=True)
    assert load_experiment(path, expected_config=expected_config)["prepared"]["source_preparation_sha256"] == original_digest
    submit_experiment(path, service=service, sampler_factory=service.sampler)
    collect_experiment(path, service=service)
    assert load_experiment(path)["state"] == "collected"


def test_status_cli_reads_only_job_json(prepared, monkeypatch, capsys):
    from broadcasting.experiments import main
    paths, _ = prepared
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Status accessed account"))
    main(["status", *map(str, paths)])
    assert '"state": "prepared"' in capsys.readouterr().out
