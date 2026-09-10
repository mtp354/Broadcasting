"""Saved-data reports retain observation identity and verify histogram statistics."""
import json
from pathlib import Path

import pytest

from broadcasting.analyze_saved_hardware import analyze, load_hardware_runs


def _write_case(directory: Path, case_id: str, *, tau_values=(0, 10), shots=100):
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 2,
        "record_id": f"test-{case_id}",
        "experiment_kind": "broadcasting",
        "timestamp": "2026-09-08T10:00:00",
        "experiment_type": "hardware",
        "job_id": "shared-job",
        "backend": "test_backend",
        "optimization_level": 3,
        "shots": shots,
        "protocol": {"M": 1, "N": 2, "alpha": 0.5, "use_qec": False,
                     "theta_samples": [[0.2]]},
        "sweep": {"axis": "tau", "values": list(tau_values)},
        "fidelities": [[0.8, 0.8] for _ in tau_values],
        "counts": [[{"00": 80, "11": 20} for _ in tau_values]],
        "metadata": {"dt": 4e-9, "execution": {
            "run_id": "test-run", "repeat_index": 0,
            "case_id": case_id,
            "receiver_delay_factors": [1, 0] if case_id == "receiver0" else [1, 1],
        }},
    }
    path = directory / f"repeat_000_{case_id}.json"
    path.write_text(json.dumps(record))
    return path


def test_analyze_retains_distinct_cases_in_one_job(tmp_path):
    results = tmp_path / "results"
    paths = [_write_case(results, case_id) for case_id in ["all", "receiver0"]]
    originals = [path.read_bytes() for path in paths]
    output = tmp_path / "analysis"

    summary = analyze(output, results_dir=results)

    assert summary["broadcasting_jobs"] == 1
    assert summary["broadcasting_records"] == 2
    assert summary["broadcasting_histograms"] == 4
    assert summary["duplicate_broadcasting_jobs"] == {}
    assert {run["execution"]["case_id"] for run in summary["runs"]} == {"all", "receiver0"}
    points = json.loads((output / "points.json").read_text())
    assert {point["execution"]["case_id"] for point in points} == {"all", "receiver0"}
    report = (output / "report.md").read_text()
    assert "repeat 0 / receiver0" in report
    assert "| test-run | 0 | shared-job | receiver0 | [1, 0] |" in report
    assert "added delay = receiver_delay_factors[i] × tau_dt" in report
    assert "not independent job repetitions" in report
    assert "Historical interpretation" not in report
    assert all(path.read_bytes() == original for path, original in zip(paths, originals))
    assert len(json.loads((output / "scaling_points.json").read_text())) == 2
    assert {path.name for path in output.iterdir()} == {
        "points.json", "summary.json", "scaling_points.json", "report.md",
    }


def test_analyze_rejects_shot_total_mismatch_before_writing_outputs(tmp_path):
    results = tmp_path / "results"
    _write_case(results, "all", shots=101)
    with pytest.raises(ValueError, match="shot total disagrees|shots disagree"):
        analyze(tmp_path / "analysis", results_dir=results)
    assert not (tmp_path / "analysis").exists()


def test_analyze_delay_sweep_without_zero_still_writes_point_statistics(tmp_path):
    results = tmp_path / "results"
    _write_case(results, "all", tau_values=(10, 20))
    output = tmp_path / "analysis"
    summary = analyze(output, results_dir=results)
    assert summary["broadcasting_histograms"] == 2
    assert summary["runs"][0]["tau0"] == []
    assert (output / "points.json").exists()
    assert json.loads((output / "scaling_points.json").read_text()) == []


def test_analyze_missing_hardware_directory_fails_clearly(tmp_path):
    with pytest.raises(ValueError, match="No saved hardware records"):
        analyze(tmp_path / "analysis", results_dir=tmp_path / "missing")


def test_load_hardware_runs_handles_nested_records_receipts_and_overlapping_roots(tmp_path):
    root = tmp_path / "execution"
    record = _write_case(root / "results", "all")
    for directory in ["receipts", "attempts"]:
        folder = root / directory
        folder.mkdir()
        (folder / "repeat_000.json").write_text('{"job_id": "receipt-not-data"}')
    runs = load_hardware_runs(tmp_path, root / "results")
    assert len(runs) == 1
    assert runs[0]["filepath"] == str(record)


def test_analyze_opt0_data_keeps_statistics_but_excludes_scaling(tmp_path):
    results = tmp_path / "results"
    path = _write_case(results, "all")
    raw = json.loads(path.read_text())
    raw["optimization_level"] = 0
    path.write_text(json.dumps(raw))
    output = tmp_path / "analysis"
    summary = analyze(output, results_dir=results)
    assert summary["broadcasting_histograms"] == 2
    assert json.loads((output / "scaling_points.json").read_text()) == []


def test_analysis_combines_separate_roots_without_pooling(tmp_path):
    first, second = tmp_path / "old", tmp_path / "new"
    _write_case(first, "old")
    _write_case(second, "new")
    summary = analyze(tmp_path / "analysis", results_dir=first, additional_results_dirs=[second])
    assert summary["broadcasting_records"] == 2
    assert summary["additional_source_directories"] == [str(second)]
    assert {run["execution"]["case_id"] for run in summary["runs"]} == {"old", "new"}


def _write_memory(directory, *, job_id="memory-job", filename="run_memory.json", shots=100):
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 2,
        "record_id": filename,
        "experiment_kind": "memory", "experiment_type": "hardware",
        "timestamp": "2026-09-08T10:00:00", "job_id": job_id,
        "backend": "test_backend", "optimization_level": 3, "shots": shots,
        "protocol": {"M": 0, "N": 1, "use_qec": True,
                     "theta_samples": [[0.2, 0.4]],
                     "state_prep": {"theta": 0.2, "phi": 0.4}},
        "sweep": {"axis": "tau", "values": [0, 10]},
        "fidelities": [[0.9], [0.7]],
        "counts": [[{"0": 90, "1": 10}, {"0": 70, "1": 30}]],
        "metadata": {"dt": 4e-9, "provenance": {"sources": [{"path": "source.json", "sha256": "a" * 64}]}},
    }
    path = directory / filename
    path.write_text(json.dumps(record))
    return path


def test_memory_only_records_use_same_numeric_pipeline_and_deduplicate(tmp_path):
    results = tmp_path / "records"
    paths = [_write_memory(results, filename=name) for name in ["run_memory.json", "run_duplicate.json"]]
    originals = [path.read_bytes() for path in paths]
    output = tmp_path / "analysis"

    summary = analyze(output, results_dir=results)

    assert summary["broadcasting_records"] == 0
    assert summary["memory_jobs"] == summary["memory_records"] == 1
    assert summary["memory_histograms"] == 2
    assert len(summary["duplicate_memory_jobs"]) == 1
    points = json.loads((output / "points.json").read_text())
    assert [point["local_fidelities"] for point in points] == [[0.9], [0.7]]
    assert all(point["pairs"] == [] for point in points)
    assert summary["memory_runs"][0]["provenance"]["sources"][0]["path"] == "source.json"
    assert json.loads((output / "scaling_points.json").read_text()) == []
    assert all(path.read_bytes() == original for path, original in zip(paths, originals))
    assert "Standalone memory records" in (output / "report.md").read_text()


def test_memory_shot_total_mismatch_fails_before_output(tmp_path):
    _write_memory(tmp_path / "records", shots=101)
    with pytest.raises(ValueError, match="shot total disagrees|shots disagree"):
        analyze(tmp_path / "analysis", results_dir=tmp_path / "records")
    assert not (tmp_path / "analysis").exists()


def test_separate_theta_histograms_preserve_covariance_and_sender_rates(tmp_path):
    path = _write_case(tmp_path / "records", "all")
    record = json.loads(path.read_text())
    record["protocol"]["theta_samples"] = [[0.2], [0.7]]
    record["counts"].append([{"00": 60, "01": 20, "10": 20} for _ in range(2)])
    record["per_theta_fidelities"] = [[[0.8, 0.8], [0.8, 0.8]]] * 2
    record["metadata"]["invalid_sender_rate"] = [[0.1, 0.2], [0.0, 0.3]]
    path.write_text(json.dumps(record))
    output = tmp_path / "analysis"

    summary = analyze(output, results_dir=path.parent)

    points = json.loads((output / "points.json").read_text())
    assert [point["invalid_sender_rate"] for point in points] == [0.1, 0.2, 0.0, 0.3]
    assert [point["global_fidelity"]["estimate"] for point in points] == [0.8, 0.8, 0.6, 0.6]
    assert points[0]["pairs"][0]["covariance"]["estimate"] == pytest.approx(0.16)
    assert points[2]["pairs"][0]["covariance"]["estimate"] == pytest.approx(-0.04)
    assert summary["runs"][0]["sender_diagnostics"] == {
        "recorded_histograms": 4, "minimum_invalid_rate": 0, "maximum_invalid_rate": 0.3,
    }
    assert "Invalid sender outcomes" in (output / "report.md").read_text()


def test_per_theta_fidelity_mismatch_is_not_hidden_by_correct_mean(tmp_path):
    path = _write_case(tmp_path / "records", "all")
    record = json.loads(path.read_text())
    record["per_theta_fidelities"] = [[[0.7, 0.8], [0.8, 0.8]]]
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="per-theta fidelities disagree"):
        analyze(tmp_path / "analysis", results_dir=path.parent)
    assert not (tmp_path / "analysis").exists()


def test_report_references_execution_evidence_without_copying_large_payloads(tmp_path):
    path = _write_case(tmp_path / "records", "all")
    record = json.loads(path.read_text())
    execution = record["metadata"]["execution"]
    execution["experiment_id"] = "experiment-1"
    execution["submitted_pub_order"] = [{"large_payload": "x" * 2000}] * 100
    execution["sampler_result_metadata"] = {"large_payload": "y" * 10000}
    execution["submission_calibration"] = {"large_payload": "z" * 10000}
    record["metadata"]["aligned_shots"] = [{"m": "0", "fid": "00"}] * 100
    path.write_text(json.dumps(record))
    original = path.read_bytes()
    output = tmp_path / "analysis"

    summary = analyze(output, results_dir=path.parent)

    assert summary["runs"][0]["dt_seconds"] == 4e-9
    assert summary["runs"][0]["filepath"] == str(path.resolve())
    expected = {key: execution[key] for key in (
        "experiment_id", "run_id", "repeat_index", "case_id", "receiver_delay_factors",
    )}
    for name in ["points", "scaling_points"]:
        records = json.loads((output / f"{name}.json").read_text())
        assert records and all(row["execution"] == expected for row in records)
    assert summary["runs"][0]["execution"] == expected
    assert summary["runs"][0]["tau0"][0]["global_fidelity"]["estimate"] == 0.8
    for output_path in output.iterdir():
        assert "large_payload" not in output_path.read_text()
        assert "aligned_shots" not in output_path.read_text()
    assert sum(output_path.stat().st_size for output_path in output.iterdir()) < 50000
    assert path.read_bytes() == original


def test_sender_rates_are_verified_and_compiled_endpoint_summary_is_compact(tmp_path):
    path = _write_case(tmp_path / "records", "all")
    record = json.loads(path.read_text())
    record["metadata"].update({
        "sender_counts": [[{"00": 90, "11": 10}, {"01": 80, "11": 20}]],
        "invalid_sender_rate": [[0.1, 0.2]],
        "initial_layout": [4, 5, 6, 7],
        "compiled_templates": [{
            "qpy_base64": "large_payload", "sha256": "a" * 64, "depth": 80,
            "layout": {"final_index_layout": [6, 7, 4, 5]},
            "operation_counts": {"cz": 20, "measure": 4},
        }],
    })
    path.write_text(json.dumps(record))
    output = tmp_path / "analysis"
    summary = analyze(output, results_dir=path.parent)
    run = summary["runs"][0]
    assert run["compiled_templates"][0]["receiver_physical_qubits"] == [4, 5]
    assert "qpy_base64" not in run["compiled_templates"][0]
    assert run["trace_endpoints"][0]["first"]["invalid_sender_rate"] == 0.1
    assert run["trace_endpoints"][0]["last"]["invalid_sender_rate"] == 0.2
    assert run["trace_endpoints"][0]["first"]["paired_differences"][0]["estimate"] == 0
    points = json.loads((output / "points.json").read_text())
    assert all(point["invalid_sender_rate_source"] == "sender_counts" for point in points)
    assert "[4, 5] | 80 / 20" in (output / "report.md").read_text()


@pytest.mark.parametrize("change", ["rate", "shots"])
def test_inconsistent_sender_evidence_fails_before_outputs(tmp_path, change):
    path = _write_case(tmp_path / "records", "all")
    record = json.loads(path.read_text())
    record["metadata"]["sender_counts"] = [[{"00": 90, "11": 10}] * 2]
    if change == "rate":
        record["metadata"]["invalid_sender_rate"] = [[0.2, 0.2]]
        message = "invalid sender rate disagrees"
    else:
        record["metadata"]["sender_counts"][0][0] = {"00": 89, "11": 10}
        message = "Sender and receiver shot totals disagree"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match=message):
        analyze(tmp_path / "analysis", results_dir=path.parent)
    assert not (tmp_path / "analysis").exists()


def test_shared_file_views_preserve_distinct_record_ids(tmp_path, monkeypatch):
    import broadcasting.analyze_saved_hardware as module
    path = tmp_path / "shared-job.json"
    records = [{"experiment_type": "hardware", "filepath": str(path),
                "record_id": record_id, "job_id": "shared-job", "experiment_kind": "broadcasting",
                "metadata": {"execution": {"case_id": record_id}}}
               for record_id in ["m1_n1", "m1_n2"]]
    monkeypatch.setattr(module, "list_runs", lambda directory: records)
    loaded = module.load_hardware_runs(tmp_path, tmp_path)
    assert [run["record_id"] for run in loaded] == ["m1_n1", "m1_n2"]
