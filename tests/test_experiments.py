"""Offline hardware experiment safety, replay, ordering and collection tests."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from qiskit.primitives.containers import BitArray, DataBin, PrimitiveResult, SamplerPubResult
from qiskit_aer import AerSimulator

from broadcasting.backend import HardwareBackend
from broadcasting.experiments import (
    attach_job, experiment_status, collect_experiment, plan_experiment, prepare_experiment,
    read_config, submit_experiment, validate_config, make_experiment_config, load_prepared_experiment,
)
from broadcasting.results import load_run


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_measured_results(tmp_path, monkeypatch):
    monkeypatch.setattr("broadcasting.experiments.DEFAULT_RESULTS_DIR", tmp_path / "results" / "records")


@pytest.fixture
def config():
    data = read_config(ROOT / "configs/hardware_repeats.json")
    data.pop("phase_design")
    data.update(schema_version=1, runtime_account="offline-test", backend="aer_simulator", shots=16, repeats=2,
                optimization_level=0, theta_samples=[[0.3], [0.8]], tau_values_dt=[0, 768])
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


@pytest.fixture
def prepared(tmp_path, config, monkeypatch):
    service = OfflineService()
    monkeypatch.setattr(HardwareBackend, "_sampler", lambda *args: pytest.fail("Preparation constructed a sampler"))
    run_dir = tmp_path / "cohort"
    bundle = prepare_experiment(config, run_dir, service=service)
    return run_dir, bundle, service


def test_checked_in_experiment_budgets_and_interleaving():
    for filename, pubs, shots in [("hardware_repeats.json", 363, 3630000),
                                  ("hardware_scaling.json", 36, 294912)]:
        config = read_config(ROOT / "configs" / filename)
        plan = plan_experiment(config)
        assert plan["total_pubs"] == pubs
        assert plan["total_shots"] == shots
        assert plan == plan_experiment(config)
        n_cases = len(config["cases"])
        for repeat in plan["repeats"]:
            order = repeat["pub_order"]
            for index in range(0, len(order), n_cases):
                block = order[index:index + n_cases]
                assert len({(row["theta_index"], row["tau_index"]) for row in block}) == 1
                assert len({row["case_id"] for row in block}) == n_cases
        config["seed"] += 1
        assert plan["repeats"] != plan_experiment(config)["repeats"]


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
        prepare_experiment(config, tmp_path / "invalid")
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


def test_config_placeholder_is_plan_only(tmp_path):
    config = read_config(ROOT / "configs/hardware_repeats.json")
    assert plan_experiment(config)["jobs"] == 3
    with pytest.raises(ValueError, match="Set runtime_account"):
        prepare_experiment(config, tmp_path / "never")


def test_prepare_is_offline_with_injected_target_and_replays_qpy(prepared):
    run_dir, bundle, service = prepared
    assert service.calls == 0
    assert bundle["review"]["delay_seconds"] == pytest.approx([0, 768e-9])
    for case in bundle["cases"]:
        original = HardwareBackend.replay_prepared(case)
        restored = HardwareBackend.replay_prepared(json.loads(json.dumps(case)))
        assert all(a == b for a, b in zip(original, restored))
        assert all(not circuit.parameters for circuit in restored)
    asymmetric = HardwareBackend.replay_prepared(bundle["cases"][1])[1]
    assert [entry.operation.duration for entry in asymmetric.data if entry.operation.name == "delay"] == [768, 0]
    assert [entry["state"] for entry in experiment_status(run_dir)["repeats"]] == ["unsubmitted"] * 2
    with pytest.raises(FileExistsError):
        prepare_experiment(bundle["config"], run_dir, service=service)


def test_submission_receipts_exist_before_collection_and_resume_never_resubmits(prepared):
    run_dir, bundle, service = prepared
    ids = submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    assert ids == ["job-1", "job-2"]
    assert submit_experiment(run_dir, service=service, sampler_factory=service.sampler) == []
    assert service.calls == 2
    assert not (run_dir / "results").exists()
    for ri in range(2):
        receipt = json.loads((run_dir / "receipts" / f"repeat_{ri:03d}.json").read_text())
        assert receipt["submitted_pub_order"] == bundle["plan"]["repeats"][ri]["pub_order"]
        assert receipt["intended_pub_order"] == receipt["submitted_pub_order"]
    # Same condition's compiled circuit is identical across shuffled repeats.
    for ri, job in enumerate(service.jobs.values()):
        order = bundle["plan"]["repeats"][ri]["pub_order"]
        for pub, index in zip(job.inputs["pubs"], order):
            assert pub[0] == HardwareBackend.replay_prepared(bundle["cases"][index["case_index"]])[index["canonical_index"]]


def test_ambiguous_submit_requires_verified_job_attachment(prepared):
    run_dir, bundle, service = prepared
    service.fail_after_submit = True
    with pytest.raises(RuntimeError, match="Connection lost"):
        submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    assert "ambiguous" in experiment_status(run_dir)["repeats"][0]["state"]
    with pytest.raises(ValueError, match="ambiguous"):
        submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    assert service.calls == 1
    job = service.jobs["job-1"]
    tags = job.tags
    job.tags = []
    with pytest.raises(ValueError, match="tags"):
        attach_job(run_dir, 0, "job-1", service=service)
    job.tags = tags
    attach_job(run_dir, 0, "job-1", service=service)
    service.fail_after_submit = False
    assert submit_experiment(run_dir, service=service, sampler_factory=service.sampler) == ["job-2"]
    assert len(collect_experiment(run_dir, service=service)) == 4


def test_collect_restores_case_point_order_and_is_append_only(prepared):
    run_dir, bundle, service = prepared
    submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    service.jobs["job-1"].fail_result = True
    with pytest.raises(RuntimeError, match="retrieval"):
        collect_experiment(run_dir, service=service)
    assert experiment_status(run_dir)["repeats"][0]["state"] == "submitted"
    service.jobs["job-1"].fail_result = False
    paths = collect_experiment(run_dir, service=service)
    before = {path: path.read_bytes() for path in paths}
    assert collect_experiment(run_dir, service=service) == []
    assert all(path.read_bytes() == data for path, data in before.items())
    assert all(row["state"] == "collected" for row in experiment_status(run_dir)["repeats"])
    for path in paths:
        run = load_run(path)
        experiment = run["metadata"]["execution"]
        for ti, row in enumerate(run["counts"]):
            for di, counts in enumerate(row):
                submitted = experiment["submitted_pub_indices"][ti * 2 + di]
                assert counts["00"] == 16 - submitted
        assert run["metadata"]["execution"]["sampler_result_metadata"]["execution"]["offline"]
        assert run["metadata"]["aligned_shots"][0][0]["num_shots"] == 16


def test_modified_preparation_cannot_submit(prepared):
    run_dir, bundle, service = prepared
    path = run_dir / "prepared.json"
    data = json.loads(path.read_text())
    data["config"]["shots"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    assert service.calls == 0


def test_cli_default_and_plan_cannot_submit(monkeypatch, capsys):
    from scripts.experiments import main
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Unexpected account lookup"))
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    main(["plan", str(ROOT / "configs/hardware_scaling.json")])
    assert json.loads(capsys.readouterr().out)["total_pubs"] == 36


def test_real_aer_accepts_bound_qpy_replay(prepared):
    from qiskit_aer.primitives import SamplerV2
    _, bundle, _ = prepared
    case = bundle["cases"][0]
    circuits = HardwareBackend.replay_prepared(case)
    container = SamplerV2(seed=42).run(circuits, shots=16).result()
    result = HardwareBackend.collect_prepared(case, container, job_id="offline-aer")
    assert result.fidelities == [[1.0, 1.0], [1.0, 1.0]]
    assert result.metadata["aligned_shots"][0][0]["num_shots"] == 16


def test_matched_layout_conflict_rejected_before_lookup(config, tmp_path, monkeypatch):
    config["cases"][0]["initial_layout"] = [0, 1, 2, 3]
    config["cases"][1]["initial_layout"] = [0, 1, 3, 2]
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Account lookup"))
    with pytest.raises(ValueError, match="same initial_layout"):
        prepare_experiment(config, tmp_path / "conflict")
    assert not (tmp_path / "conflict").exists()


def test_shared_layout_is_frozen_on_a_real_fake_target(config, tmp_path):
    from qiskit.providers.fake_provider import GenericBackendV2
    backend = GenericBackendV2(6, control_flow=True, seed=1)
    config["backend"] = backend.name
    config["theta_samples"] = [[0.3], [0.7]]
    service = SimpleNamespace(backend=lambda name: backend)
    prepared = prepare_experiment(config, tmp_path / "mapped", service=service)
    layout = prepared["review"]["shared_initial_layouts"]["M1N2"]
    assert len(layout) == 4
    for case in prepared["cases"]:
        assert case["metadata"]["initial_layout"] == layout
        for circuit in case["metadata"]["compiled_circuits"]:
            assert circuit["layout"]["initial_index_layout"][:4] == layout
    assert all(row["receiver_output_qubits"] is not None for row in prepared["review"]["mapping_review"])


def test_ambiguous_attachment_rejects_wrong_circuits_and_shots(prepared):
    run_dir, bundle, service = prepared
    service.fail_after_submit = True
    with pytest.raises(RuntimeError):
        submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    job = service.jobs["job-1"]
    pubs = job.inputs["pubs"]
    original = pubs[0]
    pubs[0] = (original[0], None, 999)
    with pytest.raises(ValueError, match="shots"):
        attach_job(run_dir, 0, job.name, service=service)
    modified = original[0].copy()
    modified.x(0)
    pubs[0] = (modified, None, original[2])
    with pytest.raises(ValueError, match="circuits/order"):
        attach_job(run_dir, 0, job.name, service=service)
    assert not (run_dir / "receipts" / "repeat_000.json").exists()


def test_changed_dt_and_concurrent_submit_fail_without_attempt(prepared):
    import fcntl
    run_dir, bundle, service = prepared
    other = AerSimulator()
    service.backend = lambda _: other
    with pytest.raises(ValueError, match="dt changed"):
        submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    assert not (run_dir / "attempts").exists()
    with (run_dir / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    assert service.calls == 0


@pytest.mark.parametrize("field,value", [("run_id", "another-run"), ("repeat_index", 1),
                                          ("shots", 999), ("submitted_pub_order", [])])
def test_misplaced_or_edited_receipts_are_rejected(prepared, field, value):
    run_dir, _, service = prepared
    submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    path = run_dir / "receipts" / "repeat_000.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    for operation in (experiment_status,
                      lambda directory: submit_experiment(directory, service=service, sampler_factory=service.sampler),
                      lambda directory: collect_experiment(directory, service=service)):
        with pytest.raises(ValueError, match="Record does not match"):
            operation(run_dir)
    assert not (run_dir / "results").exists()


def test_automatic_and_explicit_layout_do_not_hide_duplicate_conditions(config):
    duplicate = deepcopy(config["cases"][0])
    duplicate.update(id="duplicate", initial_layout=[0, 1, 2, 3])
    config["cases"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate case"):
        validate_config(config)


def test_truncated_hardware_counts_cannot_be_saved_as_complete(prepared):
    run_dir, bundle, service = prepared
    submit_experiment(run_dir, service=service, sampler_factory=service.sampler)
    job = service.jobs["job-1"]
    rows = list(job.container)
    rows[0] = SamplerPubResult(DataBin(fid=BitArray.from_samples(["00"], num_bits=2)))
    job.container = PrimitiveResult(rows)
    with pytest.raises(ValueError, match="requested shots"):
        collect_experiment(run_dir, service=service)
    assert experiment_status(run_dir)["repeats"][0]["state"] == "submitted"


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


def test_random_repeat_mixed_senders_replay_and_collect_their_actual_phases(tmp_path):
    config = make_experiment_config("scaling", backend="aer_simulator", runtime_account="offline-test",
                                  repeats=2, sender_counts=(1, 2), receiver_counts=(1, 2), tau_values_dt=[0, 50])
    config.update(shots=32, optimization_level=0)
    service = OfflineService()
    directory = tmp_path / "random-mixed"
    bundle = prepare_experiment(config, directory, service=service)
    assert bundle["schema_version"] == 2
    assert len(bundle["cases"]) == 8
    assert bundle["repeat_case_indices"] == [[0, 1, 2, 3], [4, 5, 6, 7]]
    submit_experiment(directory, service=service, sampler_factory=service.sampler)
    paths = collect_experiment(directory, service=service)
    assert len(paths) == 8
    assert collect_experiment(directory, service=service) == []
    assert submit_experiment(directory, service=service, sampler_factory=service.sampler) == []
    for path in paths:
        run = load_run(path)
        metadata = run["metadata"]["execution"]
        repeat, ci = metadata["repeat_index"], metadata["case_index"]
        samples = bundle["plan"]["repeats"][repeat]["phases"]["theta_samples_by_case"][ci]
        assert metadata["theta_samples"] == samples == run["theta_samples"]
        assert len(samples[0]) == run["M"]
        assert metadata["phase_seed"] == config["phase_design"]["seed"]
        for di, counts in enumerate(run["counts"][0]):
            position = metadata["submitted_pub_indices"][di]
            assert counts["0" * run["N"]] == 32 - position
            compiled = bundle["cases"][bundle["repeat_case_indices"][repeat][ci]]
            assert service.jobs[metadata["job_id"]].inputs["pubs"][position][0] == HardwareBackend.replay_prepared(compiled)[di]
    assert all(row["state"] == "collected" for row in experiment_status(directory)["repeats"])


def test_v2_fixed_phases_reuse_compilation_and_are_compatible_with_recovery(tmp_path):
    config = make_experiment_config("scaling", backend="aer_simulator", runtime_account="offline-test",
                                  repeats=2, sender_counts=(1, 2), receiver_counts=(1,))
    config.update(shots=16, optimization_level=0,
                  phase_design={"kind": "fixed", "samples_by_m": {"1": [[0.3]], "2": [[0.3, 0.6]]}})
    directory = tmp_path / "fixed-mixed"
    service = OfflineService()
    bundle = prepare_experiment(config, directory, service=service)
    assert len(bundle["cases"]) == 2
    assert bundle["repeat_case_indices"] == [[0, 1], [0, 1]]
    service.fail_after_submit = True
    with pytest.raises(RuntimeError, match="Connection lost"):
        submit_experiment(directory, service=service, sampler_factory=service.sampler)
    attach_job(directory, 0, "job-1", service=service)
    service.fail_after_submit = False
    assert submit_experiment(directory, service=service, sampler_factory=service.sampler) == ["job-2"]
    assert len(collect_experiment(directory, service=service)) == 4


def test_saved_delay_grid_rejects_incompatible_timing_without_rounding(tmp_path, monkeypatch):
    config = make_experiment_config("delay", backend="timed", runtime_account="offline-test")
    target = SimpleNamespace(dt=2e-9, granularity=16, pulse_alignment=16)
    service = SimpleNamespace(backend=lambda _: SimpleNamespace(target=target, num_qubits=100))
    monkeypatch.setattr(HardwareBackend, "prepare_tau_sweep", lambda *args, **kwargs: pytest.fail("Must reject before compilation"))
    with pytest.raises(ValueError, match="multiples of 16 dt"):
        prepare_experiment(config, tmp_path / "bad-timing", service=service)
    assert config["tau_values_dt"] == list(range(0, 6001, 50))
    assert not (tmp_path / "bad-timing" / "prepared.json").exists()


def test_random_phase_case_circuits_execute_on_aer_with_unit_fidelity(tmp_path):
    from qiskit_aer.primitives import SamplerV2
    config = make_experiment_config("scaling", backend="aer_simulator", runtime_account="offline-test",
                                  repeats=2, sender_counts=(1, 2), receiver_counts=(1,))
    config.update(shots=16, optimization_level=0)
    bundle = prepare_experiment(config, tmp_path / "aer-phases", service=OfflineService())
    for case in bundle["cases"]:
        circuits = HardwareBackend.replay_prepared(case)
        measured = SamplerV2(seed=22).run(circuits, shots=16).result()
        result = HardwareBackend.collect_prepared(case, measured, job_id="test-aer")
        assert result.fidelities == [[1.0]]


def test_v2_bundle_version_is_validated_even_with_consistent_digest(tmp_path):
    from broadcasting.experiments import _digest
    config = make_experiment_config("delay", backend="aer_simulator", runtime_account="offline-test", repeats=1, tau_values_dt=[0])
    config["optimization_level"] = 0
    directory = tmp_path / "versioned"
    bundle = prepare_experiment(config, directory, service=OfflineService())
    bundle["schema_version"] = 1
    (directory / "prepared.json").write_text(json.dumps(bundle))
    (directory / "prepared.sha256.json").write_text(json.dumps({"sha256": _digest(bundle)}))
    with pytest.raises(ValueError, match="versions"):
        load_prepared_experiment(directory)


def test_frozen_bundle_rejects_changed_notebook_settings(prepared):
    directory, bundle, service = prepared
    assert load_prepared_experiment(directory, expected_config=bundle["config"])["run_id"] == bundle["run_id"]
    edited = deepcopy(bundle["config"])
    edited["shots"] += 1
    with pytest.raises(ValueError, match="Notebook/config differs"):
        load_prepared_experiment(directory, expected_config=edited)
    assert service.calls == 0


def test_older_v1_bundle_without_new_review_fields_still_resumes(prepared):
    from broadcasting.experiments import _digest
    directory, bundle, service = prepared
    for key in ("cases", "phase_design", "optimization_level"):
        bundle["plan"].pop(key)
    for key in ("circuit_review", "required_delay_step_dt"):
        bundle["review"].pop(key)
    (directory / "prepared.json").write_text(json.dumps(bundle))
    (directory / "prepared.sha256.json").write_text(json.dumps({"sha256": _digest(bundle)}))
    assert submit_experiment(directory, service=service, sampler_factory=service.sampler) == ["job-1", "job-2"]
    assert len(collect_experiment(directory, service=service)) == 4
    assert all(row["state"] == "collected" for row in experiment_status(directory)["repeats"])


def test_collected_dates_follow_each_submission_and_preserve_preparation(prepared, monkeypatch):
    from broadcasting.experiments import _digest
    directory, bundle, service = prepared
    preparation_time = "2030-01-01T10:00:00+00:00"
    for case in bundle["cases"]:
        case["metadata"]["timestamp"] = preparation_time
    (directory / "prepared.json").write_text(json.dumps(bundle))
    (directory / "prepared.sha256.json").write_text(json.dumps({"sha256": _digest(bundle)}))
    times = iter(["2030-01-03T10:00:00+00:00", "2030-01-03T10:01:00+00:00",
                  "2030-01-04T11:00:00+00:00", "2030-01-04T11:01:00+00:00"])
    monkeypatch.setattr("broadcasting.experiments._now", lambda: next(times))
    submit_experiment(directory, service=service, sampler_factory=service.sampler)
    monkeypatch.setattr("broadcasting.experiments._now", lambda: "2030-01-06T12:00:00+00:00")
    for path in collect_experiment(directory, service=service):
        run = load_run(path)
        repeat = run["metadata"]["execution"]["repeat_index"]
        assert run["timestamp"] == ["2030-01-03T10:01:00+00:00", "2030-01-04T11:01:00+00:00"][repeat]
        assert run["metadata"]["prepared_at"] == preparation_time
        assert run["metadata"]["timestamp_source"] == "execution.submitted_at"
        assert run["metadata"]["execution"]["collected_at"] == "2030-01-06T12:00:00+00:00"


def test_recovered_job_date_uses_original_attempt_not_recovery(prepared, monkeypatch):
    directory, bundle, service = prepared
    attempted = "2030-01-03T10:00:00+00:00"
    monkeypatch.setattr("broadcasting.experiments._now", lambda: attempted)
    service.fail_after_submit = True
    with pytest.raises(RuntimeError, match="Connection lost"):
        submit_experiment(directory, service=service, sampler_factory=service.sampler)
    monkeypatch.setattr("broadcasting.experiments._now", lambda: "2030-01-06T12:00:00+00:00")
    attach_job(directory, 0, "job-1", service=service)
    paths = collect_experiment(directory, service=service)
    assert len(paths) == 2
    for path in paths:
        run = load_run(path)
        assert run["timestamp"] == attempted
        assert run["metadata"]["timestamp_source"] == "execution.attempted_at"
        case_index = run["metadata"]["execution"]["case_index"]
        assert run["metadata"]["prepared_at"] == bundle["cases"][case_index]["metadata"]["timestamp"]


@pytest.mark.parametrize("damage", ["invalid_json", "copied_case", "job_id", "shots", "phase", "tau", "run_id", "config_hash", "counts", "fidelities"])
def test_corrupt_existing_results_never_count_as_completed_or_get_overwritten(prepared, monkeypatch, damage):
    directory, bundle, service = prepared
    submit_experiment(directory, service=service, sampler_factory=service.sampler)
    paths = collect_experiment(directory, service=service)
    target = paths[-1]
    if damage == "invalid_json":
        target.write_text('{"truncated":')
    elif damage == "copied_case":
        target.write_bytes(paths[-2].read_bytes())
    else:
        run = json.loads(target.read_text())
        if damage == "job_id":
            run["job_id"] = "another-job"
        elif damage == "shots":
            run["shots"] += 1
        elif damage == "phase":
            run["protocol"]["theta_samples"][0][0] += 0.1
        elif damage == "tau":
            run["sweep"]["values"][1] += 1
        elif damage == "run_id":
            run["metadata"]["execution"]["run_id"] = "another-experiment-run"
        elif damage == "config_hash":
            run["metadata"]["execution"]["config_sha256"] = "wrong-hash"
        elif damage == "counts":
            run["counts"][0][0]["00"] += 1
        else:
            run["fidelities"][0][0] = 0.123
        target.write_text(json.dumps(run))
    before = target.read_bytes()
    with pytest.raises(ValueError, match="Saved result does not match"):
        experiment_status(directory)
    # Even when another output is missing, inspect every existing result before
    # retrieving any job or writing a partial collection.
    paths[0].unlink()
    monkeypatch.setattr(service, "job", lambda _: pytest.fail("Retrieved a job before validating saved files"))
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Network lookup"))
    for operation in (lambda: collect_experiment(directory, service=service), lambda: collect_experiment(directory)):
        with pytest.raises(ValueError, match="will not be overwritten"):
            operation()
    assert target.read_bytes() == before
    assert not paths[0].exists()


def test_valid_collected_results_resume_offline_including_original_v1_metadata(prepared, monkeypatch):
    directory, bundle, service = prepared
    submit_experiment(directory, service=service, sampler_factory=service.sampler)
    paths = collect_experiment(directory, service=service)
    # Simulate original v1 results that predate redundant phase/identity fields.
    for path in paths:
        run = json.loads(path.read_text())
        for key in ("case_index", "theta_samples", "phase_design", "phase_seed"):
            run["metadata"]["execution"].pop(key)
        path.write_text(json.dumps(run))
    before = {path: path.read_bytes() for path in paths}
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Complete experiment must resume offline"))
    assert collect_experiment(directory) == []
    assert all(row["state"] == "collected" for row in experiment_status(directory)["repeats"])
    assert all(path.read_bytes() == before[path] for path in paths)


@pytest.mark.parametrize("use_qec", [False, True])
def test_memory_shares_durable_submission_and_canonical_measurement_schema(tmp_path, use_qec):
    from broadcasting.experiments import make_memory_config, build_memory_circuits
    config = make_memory_config(runtime_account="offline-test", backend="aer_simulator",
                                use_qec=use_qec, theta=0.4, phi=0.8, tau_values_dt=[0, 768],
                                shots=16, optimization_level=0, repeats=2)
    circuit, bound, register = build_memory_circuits(config)
    assert circuit.num_qubits == (9 if use_qec else 1)  # Five data qubits and four syndrome ancillas.
    assert len(bound) == 2 and all(not item.parameters for item in bound)
    service = OfflineService()
    directory = tmp_path / "experiments" / "memory"
    bundle = prepare_experiment(config, directory, service=service)
    assert plan_experiment(config)["total_shots"] == 64
    assert submit_experiment(directory, service=service, sampler_factory=service.sampler) == ["job-1", "job-2"]
    assert submit_experiment(directory, service=service, sampler_factory=service.sampler) == []
    paths = collect_experiment(directory, service=service)
    assert len(paths) == 2
    for repeat, path in enumerate(paths):
        run = load_run(path)
        assert run["schema_version"] == 2 and run["experiment_kind"] == "memory"
        assert run["use_qec"] is use_qec
        assert run["state_prep"] == {"theta": 0.4, "phi": 0.8}
        assert len(run["counts"]) == 1 and len(run["counts"][0]) == 2
        assert path.parent == tmp_path / "results" / "records"
        assert not (directory / "results").exists()
        for pub_index, pub in enumerate(bundle["plan"]["repeats"][repeat]["pub_order"]):
            tau_index = pub["canonical_index"]
            assert run["counts"][0][tau_index]["0"] == 16 - pub_index
            assert run["fidelities"][tau_index] == [(16 - pub_index) / 16]
    assert collect_experiment(directory, service=service) == []
    assert all(row["state"] == "collected" for row in experiment_status(directory)["repeats"])


def test_memory_ambiguous_submission_is_recovered_without_resubmitting(tmp_path):
    from broadcasting.experiments import make_memory_config
    config = make_memory_config(runtime_account="offline-test", backend="aer_simulator",
                                use_qec=False, tau_values_dt=[0], shots=16)
    service = OfflineService()
    directory = tmp_path / "memory"
    prepare_experiment(config, directory, service=service)
    service.fail_after_submit = True
    with pytest.raises(RuntimeError, match="Connection lost"):
        submit_experiment(directory, service=service, sampler_factory=service.sampler)
    with pytest.raises(ValueError, match="ambiguous"):
        submit_experiment(directory, service=service, sampler_factory=service.sampler)
    attach_job(directory, 0, "job-1", service=service)
    assert len(collect_experiment(directory, service=service)) == 1
    assert service.calls == 1


def test_memory_reference_saves_the_shared_schema_and_noise_free_fidelity(tmp_path):
    from broadcasting.experiments import make_memory_config, run_memory_reference
    config = make_memory_config(use_qec=True, tau_values_dt=[0, 100], shots=32)
    path = run_memory_reference(config, results_dir=tmp_path / "results")
    run = load_run(path)
    assert run["experiment_kind"] == "memory"
    assert run["experiment_type"] == "simulation"
    assert run["fidelities"] == [[1.0], [1.0]]
    assert run["ideal_fidelities"] == [1.0, 1.0]
    assert run["counts"] == [[{"0": 32}, {"0": 32}]]


def test_copied_preparation_retains_checksum_and_resolves_shared_result_paths(prepared, tmp_path, monkeypatch):
    """Renamed state directories remain recoverable without rewriting frozen bundles."""
    from broadcasting.experiments import _digest
    directory, bundle, service = prepared
    original_config = deepcopy(bundle["config"])
    bundle["config"]["campaign_id"] = bundle["config"].pop("experiment_id")
    bundle["plan"]["campaign_id"] = bundle["plan"].pop("experiment_id")
    bundle["plan"]["config_sha256"] = _digest(bundle["config"])
    (directory / "prepared.json").write_text(json.dumps(bundle))
    (directory / "prepared.sha256.json").write_text(json.dumps({"sha256": _digest(bundle)}))
    frozen_bytes = (directory / "prepared.json").read_bytes()
    loaded = load_prepared_experiment(directory, expected_config=original_config)
    assert "campaign_id" not in loaded["config"]
    assert (directory / "prepared.json").read_bytes() == frozen_bytes
    submit_experiment(directory, service=service, sampler_factory=service.sampler)
    paths = collect_experiment(directory, service=service)
    mapping = {}
    for path in paths:
        run = load_run(path)
        execution = run["metadata"]["execution"]
        new_path = path.with_name(f"renamed_{path.name}")
        path.rename(new_path)
        key = f"repeat_{execution['repeat_index']:03d}_{execution['case_id']}.json"
        mapping[key] = str(new_path)
    (directory / "output_paths.json").write_text(json.dumps(mapping))
    monkeypatch.setattr("broadcasting.experiments._service", lambda _: pytest.fail("Already collected results accessed account"))
    assert collect_experiment(directory) == []
    assert all(row["state"] == "collected" for row in experiment_status(directory)["repeats"])
    assert (directory / "prepared.json").read_bytes() == frozen_bytes
