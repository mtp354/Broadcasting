"""Tests for broadcasting.backend — polymorphic Backend ABC."""

import numpy as np
import pytest

from broadcasting.protocol import ProtocolConfig, BroadcastResult
from broadcasting.backend import ExactBackend, SamplingBackend, HardwareBackend


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
        hb = HardwareBackend(service=None, backend_name="fake_backend", shots=1024)
        assert hb.backend_name == "fake_backend"
        assert hb.shots == 1024
