"""Sweep completeness, source identity and portable HPC merge evidence."""
from copy import deepcopy
import base64
import hashlib
import json
import shutil

import pytest

from broadcasting.protocol import BroadcastResult, ProtocolConfig
from broadcasting.results import (configuration_from_record, load_run, load_runs,
                                  make_run_record, write_run_json)
from broadcasting.merge_hpc_runs import _merge_group, main


GRID = [0.0, 0.25, 1.0]
SOURCE = b"# frozen simulator\n"
SOURCE_HASH = hashlib.sha256(SOURCE).hexdigest()


def _record(values, *, grid=GRID, task=None, source_hash=SOURCE_HASH, seed=7):
    config = ProtocolConfig(M=1, N=2, alpha=0.7, thetas=[0.3], p_list=values, seed=seed)
    fidelities = [[1 - value, 1 - value] for value in values]
    metadata = {"mode": "exact", "software": {"code_revision": "revision", "python": "3.test",
                    "source_sha256": {"simulation.py": source_hash}, "dependencies": {"numpy": "test"}},
                "execution": {"experiment_id": "submission", "requested_sweep_values": list(grid),
                              "sweep_task_index": task, "slurm_job_id": f"task-{task}",
                              "requested_argv": ["--p-values", "0", "0.25", "1"]},
                "task_observation": {"elapsed": 10 + (task or 0)}}
    record = make_run_record(BroadcastResult(fidelities, metadata=metadata), config)
    record["shots"] = 100
    record["counts"] = [[{"00": round(100 * (1 - value)), "11": round(100 * value)} for value in values]]
    record["per_theta_fidelities"] = [deepcopy(fidelities)]
    record["reference_fidelities"] = {"ideal": [[1.0, 1.0] for _ in values]}
    record["config"] = configuration_from_record(record)
    return record


def _job(records):
    snapshot = {"archive_format": "fixture", "archive_base64": base64.b64encode(SOURCE).decode(),
                "archive_sha256": SOURCE_HASH, "source_sha256": {"simulation.py": SOURCE_HASH},
                "code_revision": "revision"}
    prepared = {"submission_id": "submission", "argv": ["--p-values", "0", "0.25", "1"],
                "source_snapshot": snapshot}
    digest = hashlib.sha256(json.dumps(prepared, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": 3, "document_type": "hpc_execution", "state": "completed",
            "prepared": prepared, "prepared_sha256": digest, "expected_tasks": len(records),
            "measurements": records}


def test_disjoint_subsets_merge_in_requested_order_and_preserve_every_grid(tmp_path):
    last = write_run_json(_record([1.0]), tmp_path / "last.json")
    first = write_run_json(_record([0.25, 0.0]), tmp_path / "first.json")
    merged = _merge_group([last, first])
    assert merged["sweep"]["values"] == GRID
    assert merged["fidelities"] == [[1, 1], [0.75, 0.75], [0, 0]]
    assert merged["counts"] == [[{"00": 100, "11": 0}, {"00": 75, "11": 25}, {"00": 0, "11": 100}]]
    assert merged["per_theta_fidelities"] == [merged["fidelities"]]
    assert merged["reference_fidelities"] == {"ideal": [[1, 1], [1, 1], [1, 1]]}
    assert merged["config"]["sweep"] == merged["sweep"]
    assert merged["metadata"]["software"]["source_sha256"] == {"simulation.py": SOURCE_HASH}
    assert merged["metadata"]["execution"]["sweep_complete"]


def test_intended_grid_cannot_be_shortened_or_duplicated(tmp_path):
    first = write_run_json(_record([0.0, 0.25]), tmp_path / "first.json")
    last = write_run_json(_record([1.0]), tmp_path / "last.json")
    with pytest.raises(ValueError, match="Incomplete"):
        _merge_group([first])
    with pytest.raises(ValueError, match="disagrees"):
        _merge_group([first], expected_values=[0, 0.25])
    with pytest.raises(ValueError, match="Duplicate"):
        _merge_group([first, last, first])


def test_missing_recorded_grid_requires_an_explicit_complete_grid(tmp_path):
    record = _record(GRID)
    record["metadata"]["execution"].pop("requested_sweep_values")
    path = write_run_json(record, tmp_path / "unindexed.json")
    with pytest.raises(ValueError, match="intended probability grid"):
        _merge_group([path])
    assert _merge_group([path], expected_values=GRID)["sweep"]["values"] == GRID


def test_one_copied_hpc_file_merges_all_task_ids_and_keeps_source_bytes_once(tmp_path):
    records = [_record([value], task=index) for index, value in enumerate(GRID)]
    source_dir, copied_dir = tmp_path / "original", tmp_path / "copied"
    copied_dir.mkdir()
    original = write_run_json(_job(records), source_dir / "hpc_submission.json")
    copied = copied_dir / original.name
    shutil.copyfile(original, copied)
    shutil.rmtree(source_dir)
    assert len(load_runs(copied)) == 3
    merged = _merge_group([copied])
    execution = merged["metadata"]["execution"]
    assert len(execution["sources"]) == 3
    assert {source["record_id"] for source in execution["sources"]} == {record["record_id"] for record in records}
    assert {source["path"] for source in execution["sources"]} == {str(copied)}
    assert {source["sha256"] for source in execution["sources"]} == {hashlib.sha256(copied.read_bytes()).hexdigest()}
    assert [task["metadata"]["execution"]["sweep_task_index"] for task in execution["input_records"]] == [0, 1, 2]
    assert [task["metadata"]["execution"]["slurm_job_id"] for task in execution["input_records"]] == ["task-0", "task-1", "task-2"]
    assert base64.b64decode(execution["source_snapshot"]["archive_base64"]) == SOURCE
    assert json.dumps(merged).count(base64.b64encode(SOURCE).decode()) == 1
    assert len(execution["input_jobs"]) == 1
    assert execution["input_jobs"][0]["prepared"]["argv"] == records[0]["metadata"]["execution"]["requested_argv"]
    output = write_run_json(merged, tmp_path / "merged.json")
    copied.unlink()
    assert load_run(output)["fidelities"] == [[1, 1], [0.75, 0.75], [0, 0]]
    assert load_run(output)["metadata"]["execution"]["source_snapshot"] == execution["source_snapshot"]


def test_different_source_or_physical_settings_cannot_form_one_sweep(tmp_path):
    first = write_run_json(_record([0.0, 0.25]), tmp_path / "first.json")
    changed_source = write_run_json(_record([1.0], source_hash="different"), tmp_path / "source.json")
    changed_seed = write_run_json(_record([1.0], seed=8), tmp_path / "seed.json")
    for incompatible in [changed_source, changed_seed]:
        with pytest.raises(ValueError, match="different experiment"):
            _merge_group([first, incompatible])


@pytest.mark.parametrize("corruption,match", [("source", "source evidence"), ("archive", "archive checksum"),
                                               ("preparation", "preparation checksum")])
def test_hpc_source_evidence_must_match_the_executed_tasks(tmp_path, corruption, match):
    document = _job([_record([value], task=i) for i, value in enumerate(GRID)])
    if corruption == "source":
        document["measurements"][1]["metadata"]["software"]["source_sha256"] = {"simulation.py": "other"}
    elif corruption == "archive":
        document["prepared"]["source_snapshot"]["archive_base64"] = base64.b64encode(b"changed").decode()
        document["prepared_sha256"] = hashlib.sha256(json.dumps(document["prepared"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    else:
        document["prepared"]["argv"] = ["changed"]
    path = write_run_json(document, tmp_path / "hpc.json")
    original = path.read_bytes()
    with pytest.raises(ValueError, match=match):
        _merge_group([path])
    assert path.read_bytes() == original


def test_cli_defaults_to_flat_results_and_never_overwrites_explicit_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = write_run_json(_record(GRID), tmp_path / "input.json")
    original = source.read_bytes()
    main([str(source)])
    outputs = list((tmp_path / "results").iterdir())
    assert len(outputs) == 1 and outputs[0].suffix == ".json" and outputs[0].is_file()
    target = tmp_path / "review.json"
    target.write_text("original evidence")
    with pytest.raises(FileExistsError):
        main([str(source), "--output", str(target)])
    assert target.read_text() == "original evidence"
    assert source.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json", "results", "review.json"]


def test_cli_validates_all_groups_before_publishing_any_output(tmp_path):
    good = write_run_json(_record(GRID), tmp_path / "complete.json")
    incomplete = write_run_json(_record([0], seed=8), tmp_path / "incomplete.json")
    output_dir = tmp_path / "output"
    with pytest.raises(ValueError, match="Incomplete"):
        main([str(good), str(incomplete), "--output-dir", str(output_dir)])
    assert not output_dir.exists()


def test_partial_hpc_job_can_merge_with_a_matching_standalone_task(tmp_path):
    wrapped = _job([_record([0], task=0), _record([0.25], task=1)])
    wrapped.update(state="running", expected_tasks=3)
    job = write_run_json(wrapped, tmp_path / "hpc.json")
    standalone = write_run_json(_record([1], task=2), tmp_path / "task.json")
    # Put the standalone first: source selection must still find the shared archive.
    merged = _merge_group([standalone, job])
    assert merged["sweep"]["values"] == GRID
    assert merged["metadata"]["execution"]["source_snapshot"] == wrapped["prepared"]["source_snapshot"]
    assert len(merged["metadata"]["execution"]["sources"]) == 3


def test_remerging_preserves_original_derived_source_evidence(tmp_path):
    source = write_run_json(_record(GRID), tmp_path / "source.json")
    first = _merge_group([source])
    first_path = write_run_json(first, tmp_path / "first_merge.json")
    second = _merge_group([first_path])
    recovered = second["metadata"]["execution"]["input_records"][0]["metadata"]["execution"]
    assert recovered["sources"] == first["metadata"]["execution"]["sources"]
    assert recovered["input_records"] == first["metadata"]["execution"]["input_records"]


def test_archived_requirements_extend_executed_code_hashes_without_mismatch(tmp_path):
    document = _job([_record([0], task=0), _record([0.25], task=1)])
    document.update(state="running", expected_tasks=3)
    hashes = document["prepared"]["source_snapshot"]["source_sha256"]
    hashes["requirements.txt"] = "environment-requirements-evidence"
    document["prepared_sha256"] = hashlib.sha256(json.dumps(document["prepared"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    job = write_run_json(document, tmp_path / "hpc.json")
    standalone = write_run_json(_record([1], task=2), tmp_path / "standalone.json")
    merged = _merge_group([standalone, job])
    assert merged["metadata"]["execution"]["source_snapshot"]["source_sha256"] == hashes
    assert merged["metadata"]["software"]["source_sha256"] == {"simulation.py": SOURCE_HASH}
