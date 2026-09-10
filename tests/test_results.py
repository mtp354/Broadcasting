"""Round-trip tests for broadcasting.results save/load, covering the
mode-mislabeling fix (item 35) and filename-collision fix (item 36).
"""

from datetime import datetime

import numpy as np
import pytest

from broadcasting.protocol import BroadcastResult, ProtocolConfig
from broadcasting.results import (SCHEMA_VERSION, list_runs, load_run, run_paths,
                                  save_memory_run, save_run, validate_run_record,
                                  write_run_json)


def _make_config(**overrides):
    defaults = dict(M=1, N=2, alpha=1 / np.sqrt(2), thetas=[0.3], p_list=[0.0, 0.5])
    defaults.update(overrides)
    return ProtocolConfig(**defaults)


def _make_result(mode: str, **extra_meta):
    metadata = {"mode": mode, "M": 1, "N": 2, "use_qec": False, "thetas": [0.3],
                "p_list": [0.0, 0.5], "alpha": 1 / np.sqrt(2),
                "timestamp": datetime.now().isoformat()}
    metadata.update(extra_meta)
    return BroadcastResult(
        fidelities=[[0.9, 0.9], [0.6, 0.6]],
        metadata=metadata,
    )


class TestModeLabeling:
    """Regression tests for the config.n_samples-truthiness mislabeling bug."""

    def test_exact_run_labeled_exact_even_with_default_n_samples(self, tmp_path):
        # Explicit sampling configuration must not relabel an exact result.
        config = _make_config(n_samples=200)
        assert config.n_samples == 200
        result = _make_result("exact")

        path = save_run(result, config, results_dir=tmp_path)
        loaded = load_run(path)

        assert loaded["backend"] == "aer_exact"
        assert loaded["n_samples"] is None

    def test_sampling_run_labeled_sampling(self, tmp_path):
        config = _make_config(n_samples=37, seed=314)
        result = _make_result("sampled (37 trajectories)")

        path = save_run(result, config, results_dir=tmp_path)
        loaded = load_run(path)

        assert loaded["backend"] == "aer_sampling"
        assert loaded["n_samples"] == 37
        assert loaded["seed"] == 314

    def test_exact_run_labeled_exact_with_n_samples_none(self, tmp_path):
        config = _make_config(n_samples=None)
        result = _make_result("exact")

        path = save_run(result, config, results_dir=tmp_path)
        loaded = load_run(path)

        assert loaded["backend"] == "aer_exact"


class TestFilenameCollisionSafety:
    def test_default_filenames_do_not_collide(self, tmp_path):
        config = _make_config()
        result = _make_result("exact")

        path1 = save_run(result, config, results_dir=tmp_path)
        path2 = save_run(result, config, results_dir=tmp_path)

        assert path1 != path2
        assert path1.exists() and path2.exists()

    def test_explicit_filepath_still_respected(self, tmp_path):
        config = _make_config()
        result = _make_result("exact")
        target = tmp_path / "my_run.json"

        path = save_run(result, config, filepath=target)

        assert path == target
        assert path.exists()


class TestHardwareDtRecording:
    def test_dt_passed_through_metadata(self, tmp_path):
        config = _make_config()
        result = _make_result(
            "hardware (ibm_test)", backend="ibm_test", shots=100,
            job_id="abc123", sweep_values=[0, 50], dt=5e-4,
        )
        path = save_run(result, config, results_dir=tmp_path)
        loaded = load_run(path)
        assert loaded["metadata"]["dt"] == 5e-4


class TestHPCSubmissionRecord:
    def test_saved_as_hpc_submission_not_a_completed_sweep(self, tmp_path):
        config = _make_config()
        result = BroadcastResult(
            fidelities=[],
            metadata={
                "mode": "hpc (exact)", "M": 1, "N": 2, "use_qec": False,
                "command": "sbatch --export=ALL,MODE=exact,M=1,N=2 hpc/slurm_broadcast.sh",
                "submitted": False, "job_id": None,
                "timestamp": datetime.now().isoformat(),
            },
        )
        path = save_run(result, config, results_dir=tmp_path)
        loaded = load_run(path)
        assert loaded["experiment_type"] == "hpc_submission"
        assert loaded["fidelities"] == []
        assert loaded["metadata"]["submitted"] is False
        assert "sbatch" in loaded["metadata"]["command"]


class TestExecutedSettings:
    def test_metadata_wins_over_stale_config(self, tmp_path):
        result = _make_result("sampled (7 trajectories)", n_samples=7, seed=314,
                              linear_feedforward=False, outcomes_list=[1])
        path = save_run(result, _make_config(n_samples=200, seed=0), results_dir=tmp_path)
        loaded = load_run(path)
        assert (loaded["n_samples"], loaded["seed"]) == (7, 314)
        assert loaded["linear_feedforward"] is False
        assert loaded["outcomes_list"] == [1]

    def test_slurm_repeated_saves_remain_unique(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SLURM_JOB_ID", "123")
        monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "4")
        result, config = _make_result("exact"), _make_config()
        first = save_run(result, config, results_dir=tmp_path)
        second = save_run(result, config, results_dir=tmp_path)
        assert first != second
        assert "_123_4_" in first.name

    def test_explicit_existing_path_is_never_overwritten(self, tmp_path):
        path = tmp_path / "old.json"
        path.write_text("original")
        with pytest.raises(FileExistsError):
            save_run(_make_result("exact"), _make_config(), filepath=path)
        assert path.read_text() == "original"
        assert list(tmp_path.iterdir()) == [path]

    def test_failed_serialization_publishes_nothing(self, tmp_path):
        from broadcasting.results import write_run_json
        with pytest.raises(ValueError):
            write_run_json({"bad": float("nan")}, tmp_path / "invalid.json")
        assert list(tmp_path.iterdir()) == []


def test_broadcast_record_contains_common_schema_and_execution_identity(tmp_path):
    result = _make_result("exact", execution={"experiment_id": "delay", "case_id": "m1_n2"})
    path = save_run(result, _make_config(), results_dir=tmp_path)
    run = load_run(path)
    assert run["schema_version"] == SCHEMA_VERSION
    assert run["experiment_kind"] == "broadcasting"
    assert run["record_id"]
    assert run["sweep"]["unit"] == "probability"
    assert run["metadata"]["execution"]["case_id"] == "m1_n2"
    assert (run["M"], run["N"], run["nt"]) == (1, 2, 1)


def _memory_payload(**updates):
    payload = {"experiment_type": "hardware", "backend": "ibm_test", "job_id": "memory-job",
               "shots": 100, "optimization_level": 3, "use_qec": True,
               "state_prep": {"theta": 0.7, "phi": 0.2}, "tau_values": [0, 50],
               "backend_fidelities": [0.9, 0.75], "ideal_fidelities": [1.0, 1.0],
               "backend_counts": [{"0": 90, "1": 10}, {"0": 75, "1": 25}],
               "metadata": {"dt": 4e-9, "execution": {"experiment_id": "memory"}}}
    payload.update(updates)
    return payload


def test_memory_sweep_uses_same_loader_counts_and_reference_grid(tmp_path):
    source = _memory_payload()
    path = save_memory_run(source, results_dir=tmp_path)
    run = load_run(path)
    assert run["experiment_kind"] == "memory"
    assert (run["M"], run["N"]) == (0, 1)
    assert run["fidelities"] == [[0.9], [0.75]]
    assert run["counts"] == [source["backend_counts"]]
    assert run["reference_fidelities"] == {"ideal": [[1.0], [1.0]]}
    assert run["ideal_fidelities"] == [1.0, 1.0]
    assert run["state_prep"] == source["state_prep"]
    assert run["theta_samples"] == [[0.7, 0.2]]
    assert run["entries"][1] == {"theta_idx": 0, "thetas": [0.7, 0.2], "tau": 50,
                                  "fidelities": [0.75], "counts": {"0": 75, "1": 25}}


def test_memory_simulation_without_external_reference(tmp_path):
    source = _memory_payload(experiment_type="simulation", backend="aer_simulator",
                             job_id=None, use_qec=False, ideal_fidelities=None)
    run = load_run(save_memory_run(source, results_dir=tmp_path))
    assert run["experiment_type"] == "simulation"
    assert run["use_qec"] is False
    assert run["ideal_fidelities"] is None


def test_memory_encoding_must_be_explicit_and_writes_are_exclusive(tmp_path):
    with pytest.raises(ValueError, match="use_qec"):
        save_memory_run(_memory_payload(use_qec=None), results_dir=tmp_path)
    assert not list(tmp_path.iterdir())
    target = save_memory_run(_memory_payload(), filepath=tmp_path / "memory.json")
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        save_memory_run(_memory_payload(), filepath=target)
    assert target.read_bytes() == original


def test_record_discovery_uses_schema_and_filters_physical_experiment_kind(tmp_path):
    broadcast = save_run(_make_result("exact"), _make_config(), filepath=tmp_path / "custom.json")
    memory = save_memory_run(_memory_payload(), filepath=tmp_path / "measured.json")
    write_run_json({"schema_version": SCHEMA_VERSION, "config": {}}, tmp_path / "plan.json")
    save_run(_make_result("exact"), _make_config(), filepath=tmp_path / "nested" / "ignored.json")
    assert set(run_paths(tmp_path)) == {broadcast, memory}
    assert len(list_runs(tmp_path)) == 2
    assert [r["filepath"] for r in list_runs(tmp_path, experiment_kind="memory")] == [str(memory)]
    assert len(list_runs(tmp_path, experiment_type="simulation")) == 1
    assert len(list_runs(tmp_path, backend="ibm_test")) == 1


def test_loader_rejects_unmigrated_input_without_rewriting_it(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"experiment_type": "simulation", "sweep": {}}')
    original = path.read_bytes()
    with pytest.raises(ValueError, match="schema_version"):
        load_run(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("field,value,match", [
    ("fidelities", [[0.9, 0.7]], "shape"),
    ("fidelities", [[float("nan")], [0.75]], "finite"),
    ("counts", [[{"0": 89, "1": 10}, {"0": 75, "1": 25}]], "shot total"),
])
def test_malformed_measurements_are_rejected(tmp_path, field, value, match):
    import json
    record = json.loads(save_memory_run(_memory_payload(), results_dir=tmp_path).read_text())
    record[field] = value
    with pytest.raises(ValueError, match=match):
        validate_run_record(record)


def test_builders_are_pure_and_save_round_trips_their_effective_settings(tmp_path, monkeypatch):
    from broadcasting.results import make_run_record, make_memory_record
    monkeypatch.chdir(tmp_path)
    record = make_run_record(_make_result("sampled", seed=7, n_samples=19), _make_config(),
                             metadata={"execution": {"experiment_id": "standalone"}})
    memory = make_memory_record(_memory_payload())
    assert list(tmp_path.iterdir()) == []
    assert record["config"]["seed"] == 7
    assert record["config"]["n_samples"] == 19
    assert memory["config"]["protocol"]["state_prep"] == {"theta": 0.7, "phi": 0.2}
    assert record["metadata"]["execution"]["experiment_id"] == "standalone"


def test_job_case_expansion_requires_explicit_identity_and_preserves_physical_path(tmp_path):
    from broadcasting.results import make_run_record
    first = make_run_record(_make_result("exact"), _make_config())
    second = make_run_record(_make_result("exact"), _make_config())
    second["protocol"]["theta_samples"] = [[0.7]]
    wrapper = {"schema_version": 3, "document_type": "execution", "state": "collected",
               "experiment_kind": "broadcasting", "prepared": {"config": {"shots": 100}},
               "receipt": {"job_id": "job"}, "measurements": [first, second]}
    path = write_run_json(wrapper, tmp_path / "job.json")
    runs = list_runs(tmp_path)
    assert len(runs) == 2
    assert {r["record_id"] for r in runs} == {first["record_id"], second["record_id"]}
    assert {r["filepath"] for r in runs} == {str(path)}
    assert all(r["execution_record"]["receipt"] == {"job_id": "job"} for r in runs)
    with pytest.raises(ValueError, match="specify record_id"):
        load_run(path)
    selected = load_run(path, record_id=second["record_id"])
    assert selected["theta_samples"] == [[0.7]]
    assert selected["fidelities"] == second["fidelities"]
    with pytest.raises(ValueError, match="No matching"):
        load_run(path, record_id="absent")


def test_single_case_job_and_pending_job_discovery(tmp_path):
    from broadcasting.results import make_memory_record
    record = make_memory_record(_memory_payload())
    path = write_run_json({"schema_version": 3, "document_type": "execution",
                          "state": "collected", "experiment_kind": "memory",
                          "measurements": [record]}, tmp_path / "memory.json")
    pending = write_run_json({"schema_version": 3, "document_type": "execution",
                             "state": "submitted", "measurements": []}, tmp_path / "pending.json")
    assert load_run(path)["record_id"] == record["record_id"]
    assert run_paths(tmp_path) == [path]
    assert len(list_runs(tmp_path, experiment_kind="memory")) == 1
    with pytest.raises(ValueError, match="No matching"):
        load_run(pending)


def test_rounded_summary_is_opt_in_and_does_not_fabricate_measurements(tmp_path):
    record = {"schema_version": 2, "record_id": "summary", "experiment_kind": "convergence_summary",
              "experiment_type": "simulation", "config": {"N": 2}, "sample_counts": [50, 100],
              "errors_per_receiver": [[0.05, 0.06], [0.03, 0.04]], "fidelities": None,
              "counts": None, "raw_fidelity_grids_available": False}
    path = write_run_json(record, tmp_path / "summary.json")
    assert list_runs(tmp_path) == []
    assert run_paths(tmp_path) == []
    assert list_runs(tmp_path, include_summaries=True)[0]["fidelities"] is None
    assert list_runs(tmp_path, experiment_kind="convergence_summary")[0]["record_id"] == "summary"
    assert load_run(path)["errors_per_receiver"] == record["errors_per_receiver"]
    record["fidelities"] = [[1.0, 1.0]]
    with pytest.raises(ValueError, match="unavailable"):
        validate_run_record(record)


def test_list_runs_reads_each_physical_json_once(monkeypatch, tmp_path):
    import broadcasting.results as results
    save_run(_make_result("exact"), _make_config(), results_dir=tmp_path)
    save_memory_run(_memory_payload(), results_dir=tmp_path)
    original = results._read_document
    reads = []
    def read(path):
        reads.append(path)
        return original(path)
    monkeypatch.setattr(results, "_read_document", read)
    assert len(list_runs(tmp_path)) == 2
    assert len(reads) == len(set(reads)) == 2


def _hpc_document(records, *, state="running", expected_tasks=2):
    import base64
    import gzip
    import hashlib
    source = b"# frozen simulator source\nN = 2\n"
    archive = gzip.compress(source, mtime=0)
    return {"schema_version": 3, "document_type": "hpc_execution", "state": state,
            "expected_tasks": expected_tasks,
            "prepared": {"submission_id": "portable",
                         "argv": ["--M", "1", "--N", "2", "--p_list", "0.0,0.5"],
                         "source_snapshot": {"archive_base64": base64.b64encode(archive).decode(),
                                             "archive_sha256": hashlib.sha256(archive).hexdigest(),
                                             "source_sha256": {"simulation.py": hashlib.sha256(source).hexdigest()},
                                             "code_revision": "recorded-revision"}},
            "prepared_sha256": "fixture-hash", "measurements": records}


def test_partially_finished_hpc_job_retains_completed_tasks_and_their_source_after_copy(tmp_path):
    import base64
    import gzip
    import shutil
    from broadcasting.results import make_run_record
    source_dir = tmp_path / "source"
    copied_dir = tmp_path / "copied"
    copied_dir.mkdir()
    record = make_run_record(_make_result("sampled", seed=31, n_samples=100), _make_config(),
                             metadata={"execution": {"sweep_task_index": 0, "slurm_job_id": "123"}})
    original = write_run_json(_hpc_document([record]), source_dir / "hpc_portable.json")
    copied = copied_dir / "hpc_portable.json"
    shutil.copyfile(original, copied)
    shutil.rmtree(source_dir)
    loaded = list_runs(copied_dir)
    assert len(loaded) == 1
    assert loaded[0]["record_id"] == record["record_id"]
    assert loaded[0]["fidelities"] == record["fidelities"]
    assert loaded[0]["config"] == record["config"]
    assert loaded[0]["filepath"] == str(copied)
    assert loaded[0]["execution_record"]["state"] == "running"
    assert loaded[0]["execution_record"]["expected_tasks"] == 2
    assert loaded[0]["metadata"]["execution"]["sweep_task_index"] == 0
    snapshot = loaded[0]["execution_record"]["prepared"]["source_snapshot"]
    assert gzip.decompress(base64.b64decode(snapshot["archive_base64"])) == b"# frozen simulator source\nN = 2\n"
    assert load_run(copied)["record_id"] == record["record_id"]
    assert run_paths(copied_dir) == [copied]


def test_completed_hpc_tasks_share_one_file_but_keep_independent_identities(tmp_path):
    from broadcasting.results import make_run_record
    first = make_run_record(_make_result("sampled", seed=11), _make_config(),
                            metadata={"execution": {"sweep_task_index": 0}})
    second = make_run_record(_make_result("sampled", seed=12), _make_config(),
                             metadata={"execution": {"sweep_task_index": 1}})
    path = write_run_json(_hpc_document([first, second], state="completed"), tmp_path / "hpc.json")
    runs = list_runs(tmp_path, experiment_type="simulation")
    assert {run["record_id"] for run in runs} == {first["record_id"], second["record_id"]}
    assert {run["seed"] for run in runs} == {11, 12}
    assert all(run["filepath"] == str(path) for run in runs)
    with pytest.raises(ValueError, match="specify record_id"):
        load_run(path)
    assert load_run(path, record_id=second["record_id"])["seed"] == 12


@pytest.mark.parametrize("invalid", ["partial", "missing", "duplicate", "receipt"])
def test_hpc_loader_rejects_invalid_task_payloads_without_silently_dropping_them(tmp_path, invalid):
    from copy import deepcopy
    from broadcasting.results import make_run_record
    good = make_run_record(_make_result("exact"), _make_config())
    bad = deepcopy(good)
    bad["record_id"] = "other"
    if invalid == "partial":
        bad["fidelities"] = [[0.9, 0.9]]
        match = "shape"
    elif invalid == "missing":
        bad = None
        match = "complete record objects"
    elif invalid == "duplicate":
        bad["record_id"] = good["record_id"]
        match = "record_id values must be unique"
    else:
        bad = make_run_record(BroadcastResult([], metadata={"mode": "hpc (exact)"}), _make_config())
        match = "completed measurement grids"
    path = write_run_json(_hpc_document([good, bad]), tmp_path / "hpc.json")
    saved = path.read_bytes()
    with pytest.raises(ValueError, match=match):
        list_runs(tmp_path)
    assert path.read_bytes() == saved


def test_prepared_hpc_submission_is_not_yet_a_measurement(tmp_path):
    from broadcasting.results import make_run_record
    path = write_run_json(_hpc_document([], state="prepared"), tmp_path / "hpc.json")
    assert list_runs(tmp_path) == []
    assert run_paths(tmp_path) == []
    with pytest.raises(ValueError, match="No matching"):
        load_run(path)
    record = make_run_record(_make_result("exact"), _make_config())
    write_run_json(_hpc_document([record], state="prepared"), tmp_path / "inconsistent.json")
    with pytest.raises(ValueError, match="Prepared HPC documents"):
        list_runs(tmp_path)
