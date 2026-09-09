"""Offline hardware campaign safety, replay, ordering and collection tests."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from qiskit.primitives.containers import BitArray, DataBin, PrimitiveResult, SamplerPubResult
from qiskit_aer import AerSimulator

from broadcasting.backend import HardwareBackend
from broadcasting.hardware_campaign import (
    attach_job, campaign_status, collect_campaign, plan_campaign, prepare_campaign,
    read_config, submit_campaign, validate_config,
)
from broadcasting.results import load_run


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    data = read_config(ROOT / "configs/hardware_repeats.json")
    data.update(runtime_account="offline-test", backend="aer_simulator", shots=16, repeats=2,
                optimization_level=0, theta_samples=[[0.3], [0.8]], tau_values_dt=[0, 768])
    data["cases"] = data["cases"][:2]
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
    bundle = prepare_campaign(config, run_dir, service=service)
    return run_dir, bundle, service


def test_checked_in_campaign_budgets_and_interleaving():
    for filename, pubs, shots in [("hardware_repeats.json", 162, 663552),
                                  ("hardware_scaling.json", 18, 73728)]:
        config = read_config(ROOT / "configs" / filename)
        plan = plan_campaign(config)
        assert plan["total_pubs"] == pubs
        assert plan["total_shots"] == shots
        assert plan == plan_campaign(config)
        n_cases = len(config["cases"])
        for repeat in plan["repeats"]:
            order = repeat["pub_order"]
            for index in range(0, len(order), n_cases):
                block = order[index:index + n_cases]
                assert len({(row["theta_index"], row["tau_index"]) for row in block}) == 1
                assert len({row["case_id"] for row in block}) == n_cases
        config["seed"] += 1
        assert plan["repeats"] != plan_campaign(config)["repeats"]


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
    monkeypatch.setattr("broadcasting.hardware_campaign._service", lambda _: pytest.fail("Network lookup"))
    with pytest.raises(ValueError):
        prepare_campaign(config, tmp_path / "invalid")
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
    assert plan_campaign(config)["jobs"] == 3
    with pytest.raises(ValueError, match="Set runtime_account"):
        prepare_campaign(config, tmp_path / "never")


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
    assert [entry["state"] for entry in campaign_status(run_dir)["repeats"]] == ["unsubmitted"] * 2
    with pytest.raises(FileExistsError):
        prepare_campaign(bundle["config"], run_dir, service=service)


def test_submission_receipts_exist_before_collection_and_resume_never_resubmits(prepared):
    run_dir, bundle, service = prepared
    ids = submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    assert ids == ["job-1", "job-2"]
    assert submit_campaign(run_dir, service=service, sampler_factory=service.sampler) == []
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
        submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    assert "ambiguous" in campaign_status(run_dir)["repeats"][0]["state"]
    with pytest.raises(ValueError, match="ambiguous"):
        submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    assert service.calls == 1
    job = service.jobs["job-1"]
    tags = job.tags
    job.tags = []
    with pytest.raises(ValueError, match="tags"):
        attach_job(run_dir, 0, "job-1", service=service)
    job.tags = tags
    attach_job(run_dir, 0, "job-1", service=service)
    service.fail_after_submit = False
    assert submit_campaign(run_dir, service=service, sampler_factory=service.sampler) == ["job-2"]
    assert len(collect_campaign(run_dir, service=service)) == 4


def test_collect_restores_case_point_order_and_is_append_only(prepared):
    run_dir, bundle, service = prepared
    submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    service.jobs["job-1"].fail_result = True
    with pytest.raises(RuntimeError, match="retrieval"):
        collect_campaign(run_dir, service=service)
    assert campaign_status(run_dir)["repeats"][0]["state"] == "submitted"
    service.jobs["job-1"].fail_result = False
    paths = collect_campaign(run_dir, service=service)
    before = {path: path.read_bytes() for path in paths}
    assert collect_campaign(run_dir, service=service) == []
    assert all(path.read_bytes() == data for path, data in before.items())
    assert all(row["state"] == "collected" for row in campaign_status(run_dir)["repeats"])
    for path in paths:
        run = load_run(path)
        campaign = run["metadata"]["campaign"]
        for ti, row in enumerate(run["counts"]):
            for di, counts in enumerate(row):
                submitted = campaign["submitted_pub_indices"][ti * 2 + di]
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
        submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    assert service.calls == 0


def test_cli_default_and_plan_cannot_submit(monkeypatch, capsys):
    from scripts.hardware_campaign import main
    monkeypatch.setattr("broadcasting.hardware_campaign._service", lambda _: pytest.fail("Unexpected account lookup"))
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    main(["plan", str(ROOT / "configs/hardware_scaling.json")])
    assert json.loads(capsys.readouterr().out)["total_pubs"] == 18


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
    monkeypatch.setattr("broadcasting.hardware_campaign._service", lambda _: pytest.fail("Account lookup"))
    with pytest.raises(ValueError, match="same initial_layout"):
        prepare_campaign(config, tmp_path / "conflict")
    assert not (tmp_path / "conflict").exists()


def test_shared_layout_is_frozen_on_a_real_fake_target(config, tmp_path):
    from qiskit.providers.fake_provider import GenericBackendV2
    backend = GenericBackendV2(6, control_flow=True, seed=1)
    config["backend"] = backend.name
    config["theta_samples"] = [[0.3], [0.7]]
    service = SimpleNamespace(backend=lambda name: backend)
    prepared = prepare_campaign(config, tmp_path / "mapped", service=service)
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
        submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
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
        submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    assert not (run_dir / "attempts").exists()
    with (run_dir / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    assert service.calls == 0


@pytest.mark.parametrize("field,value", [("run_id", "another-run"), ("repeat_index", 1),
                                          ("shots", 999), ("submitted_pub_order", [])])
def test_misplaced_or_edited_receipts_are_rejected(prepared, field, value):
    run_dir, _, service = prepared
    submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    path = run_dir / "receipts" / "repeat_000.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    for operation in (campaign_status,
                      lambda directory: submit_campaign(directory, service=service, sampler_factory=service.sampler),
                      lambda directory: collect_campaign(directory, service=service)):
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
    submit_campaign(run_dir, service=service, sampler_factory=service.sampler)
    job = service.jobs["job-1"]
    rows = list(job.container)
    rows[0] = SamplerPubResult(DataBin(fid=BitArray.from_samples(["00"], num_bits=2)))
    job.container = PrimitiveResult(rows)
    with pytest.raises(ValueError, match="requested shots"):
        collect_campaign(run_dir, service=service)
    assert campaign_status(run_dir)["repeats"][0]["state"] == "submitted"
