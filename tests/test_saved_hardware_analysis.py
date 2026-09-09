"""Read-only campaign analysis preserves shared-job cases and recorded shot totals."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import pytest

from scripts.analyze_saved_hardware import analyze, load_hardware_runs


def _write_case(directory: Path, case_id: str, *, tau_values=(0, 10), shots=100):
    directory.mkdir(parents=True, exist_ok=True)
    record = {
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
        "metadata": {"dt": 4e-9, "campaign": {
            "campaign_id": "test-campaign", "run_id": "test-run", "repeat_index": 0,
            "case_id": case_id,
            "receiver_delay_factors": [1, 0] if case_id == "receiver0" else [1, 1],
        }},
    }
    path = directory / f"repeat_000_{case_id}.json"
    path.write_text(json.dumps(record))
    return path


def test_analyze_campaign_retains_distinct_cases_in_one_job(tmp_path):
    results = tmp_path / "results"
    paths = [_write_case(results, case_id) for case_id in ["all", "receiver0"]]
    originals = [path.read_bytes() for path in paths]
    output = tmp_path / "analysis"

    summary = analyze(output, results_dir=results)

    assert summary["broadcasting_jobs"] == 1
    assert summary["broadcasting_records"] == 2
    assert summary["broadcasting_histograms"] == 4
    assert summary["duplicate_broadcasting_jobs"] == {}
    assert {run["campaign"]["case_id"] for run in summary["runs"]} == {"all", "receiver0"}
    points = json.loads((output / "points.json").read_text())
    assert {point["campaign"]["case_id"] for point in points} == {"all", "receiver0"}
    report = (output / "report.md").read_text()
    assert "repeat 0 / receiver0" in report
    assert "| test-run | 0 | shared-job | receiver0 | [1, 0] |" in report
    assert "added delay = receiver_delay_factors[i] × tau_dt" in report
    assert "not independent job repetitions" in report
    assert "Historical interpretation" not in report
    assert all(path.read_bytes() == original for path, original in zip(paths, originals))
    assert (output / "tau0_fidelities.png").exists()
    assert len(json.loads((output / "scaling_points.json").read_text())) == 2
    assert len(list((output / "delay_sweeps").glob("*.png"))) == 2
    assert not list(output.rglob("*.pdf"))


def test_analyze_rejects_shot_total_mismatch_before_writing_outputs(tmp_path):
    results = tmp_path / "results"
    _write_case(results, "all", shots=101)
    with pytest.raises(ValueError, match="shots disagree"):
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
    assert not (output / "tau0_fidelities.png").exists()


def test_analyze_missing_hardware_directory_fails_clearly(tmp_path):
    with pytest.raises(ValueError, match="No saved hardware records"):
        analyze(tmp_path / "analysis", results_dir=tmp_path / "missing")


def test_load_hardware_runs_handles_nested_campaigns_receipts_and_overlapping_roots(tmp_path):
    root = tmp_path / "campaign"
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
    assert (output / "joint_and_worst_tau0.png").exists()
    assert not (output / "tau0_fidelities.png").exists()


def test_analysis_combines_separate_roots_without_pooling(tmp_path):
    first, second = tmp_path / "old", tmp_path / "new"
    _write_case(first, "old")
    _write_case(second, "new")
    summary = analyze(tmp_path / "analysis", results_dir=first, additional_results_dirs=[second])
    assert summary["broadcasting_records"] == 2
    assert summary["additional_source_directories"] == [str(second)]
    assert {run["campaign"]["case_id"] for run in summary["runs"]} == {"old", "new"}
