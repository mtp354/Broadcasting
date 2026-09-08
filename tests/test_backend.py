"""Tests for broadcasting.backend — polymorphic Backend ABC."""

import numpy as np
import pytest

from broadcasting.protocol import ProtocolConfig, BroadcastResult
from broadcasting.backend import ExactBackend, SamplingBackend, HPCBackend, HardwareBackend


def _base_config(**overrides) -> ProtocolConfig:
    defaults = dict(
        M=1, N=2,
        alpha=1.0 / np.sqrt(3),
        thetas=[np.pi / 4],
        p_list=[0.0, 0.5],
        use_qec=False,
        outcomes_list=[0],
    )
    defaults.update(overrides)
    return ProtocolConfig(**defaults)


class TestExactBackend:
    def test_returns_broadcast_result(self):
        result = ExactBackend().run(_base_config())
        assert isinstance(result, BroadcastResult)

    def test_fidelity_shape(self):
        config = _base_config(p_list=[0.0, 0.25, 0.5])
        result = ExactBackend().run(config)
        fids = np.array(result.fidelities)
        assert fids.shape == (3, 2)  # 3 p-values, N=2 receivers

    def test_metadata_mode(self):
        result = ExactBackend().run(_base_config())
        assert "exact" in result.metadata["mode"].lower()

    def test_zero_noise_high_fidelity(self):
        config = _base_config(p_list=[0.0])
        result = ExactBackend().run(config)
        for f in result.fidelities[0]:
            assert f > 0.99

    def test_qec_mode(self):
        config = _base_config(use_qec=True, p_list=[0.0])
        result = ExactBackend().run(config)
        assert "exact" in result.metadata["mode"].lower()
        for f in result.fidelities[0]:
            assert f > 0.99


class TestSamplingBackend:
    def test_requires_qec(self):
        config = _base_config(use_qec=False)
        with pytest.raises(ValueError, match="QEC"):
            SamplingBackend(n_samples=100).run(config)

    def test_returns_result_with_qec(self):
        config = _base_config(use_qec=True, p_list=[0.0])
        result = SamplingBackend(n_samples=200, seed=0).run(config)
        assert isinstance(result, BroadcastResult)
        assert "sampl" in result.metadata["mode"].lower()

    def test_zero_noise_high_fidelity(self):
        config = _base_config(use_qec=True, p_list=[0.0])
        result = SamplingBackend(n_samples=500, seed=0).run(config)
        for f in result.fidelities[0]:
            assert f > 0.99


class TestHardwareBackend:
    def test_init_stores_parameters(self):
        # Just test construction (no actual IBM service needed)
        hb = HardwareBackend(
            service=None,
            backend_name="fake_backend",
            shots=1024,
            optimization_level=1,
        )
        assert hb.backend_name == "fake_backend"
        assert hb.shots == 1024
        assert hb.optimization_level == 1


class TestHPCBackend:
    def test_rejects_invalid_mode(self):
        with pytest.raises(ValueError, match="mode"):
            HPCBackend(mode="bogus")

    def test_run_without_submit_never_calls_subprocess(self, monkeypatch):
        import subprocess

        def _boom(*a, **k):
            raise AssertionError("subprocess.run should not be called when submit=False")

        monkeypatch.setattr(subprocess, "run", _boom)
        result = HPCBackend(submit=False).run(_base_config())
        assert isinstance(result, BroadcastResult)
        assert result.fidelities == []
        assert result.metadata["submitted"] is False
        assert result.metadata["job_id"] is None

    def test_build_command_maps_config_fields(self):
        config = _base_config(
            M=2, N=3, alpha=0.6, thetas=[0.1, 0.2], p_list=[0.0, 0.5, 1.0],
            use_qec=True, outcomes_list=[1, 0], seed=7,
        )
        cmd = HPCBackend(mode="sampling").build_command(config)
        joined = " ".join(cmd)
        assert cmd[0] == "sbatch"
        assert "MODE=sampling" in joined
        assert "M=2" in joined
        assert "N=3" in joined
        assert "P_MIN=0.0" in joined
        assert "P_MAX=1.0" in joined
        assert "P_STEPS=3" in joined
        assert "USE_QEC=1" in joined
        assert "ALPHA=0.6" in joined
        assert "SEED=7" in joined
        assert cmd[-1] == "hpc/slurm_broadcast.sh"

    def test_array_sets_slurm_array_range(self):
        config = _base_config(p_list=[0.0, 0.25, 0.5, 0.75])
        cmd = HPCBackend(array=True, concurrency=2).build_command(config)
        assert "--array=0-3%2" in cmd

    def test_no_array_by_default(self):
        config = _base_config(p_list=[0.0, 0.5])
        cmd = HPCBackend().build_command(config)
        assert not any(c.startswith("--array") for c in cmd)

    def test_submit_true_invokes_subprocess_and_parses_job_id(self, monkeypatch):
        import subprocess

        class _FakeCompleted:
            stdout = "Submitted batch job 12345\n"

        captured = {}

        def _fake_run(cmd, capture_output, text, check):
            captured["cmd"] = cmd
            return _FakeCompleted()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        result = HPCBackend(submit=True).run(_base_config())
        assert result.metadata["submitted"] is True
        assert result.metadata["job_id"] == "12345"
        assert captured["cmd"][0] == "sbatch"
