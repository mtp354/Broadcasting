"""Round-trip tests for broadcasting.results save/load, covering the
mode-mislabeling fix (item 35) and filename-collision fix (item 36).
"""

from datetime import datetime

import numpy as np
import pytest

from broadcasting.protocol import BroadcastResult, ProtocolConfig
from broadcasting.results import load_run, save_run


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
            job_id="abc123", tau=0, dt=5e-4,
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
