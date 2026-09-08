"""Tests for broadcasting.backend — polymorphic Backend ABC."""

from types import SimpleNamespace

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

    def test_compute_invalid_sender_rate(self):
        # M=1, N=2: nq=2, valid sender values are 0, 1, 2. Value 3 ('11') is invalid.
        counts = {"00": 300, "01": 300, "10": 300, "11": 100}
        rate = HardwareBackend._compute_invalid_sender_rate(counts, M=1, N=2)
        assert rate == pytest.approx(0.10)

        # M=2, N=1: nq=1, valid values are 0, 1. Length L=2. All combinations valid.
        counts_m2 = {"00": 250, "01": 250, "10": 250, "11": 250}
        rate_m2 = HardwareBackend._compute_invalid_sender_rate(counts_m2, M=2, N=1)
        assert rate_m2 == pytest.approx(0.0)

    def test_run_tau_sweep_transpiles_once_per_theta_sample(self, monkeypatch):
        # Regression test: binding tau *before* transpiling meant transpiling
        # once per tau value (very slow / can hang for dynamic circuits).
        # Transpiling once (tau left free) and binding the ISA circuit per tau
        # value is what actually gets submitted.
        call_counts = {"pm_run": 0}

        class _FakePM:
            def run(self, qc):
                call_counts["pm_run"] += 1
                return qc

        monkeypatch.setattr(
            "qiskit.transpiler.generate_preset_pass_manager",
            lambda **kwargs: _FakePM(),
        )

        class _FakePubResult:
            def __init__(self):
                self.data = SimpleNamespace(fid=self)

            def get_counts(self):
                return {"00": 100}

        class _FakeJob:
            def __init__(self, n_pubs):
                self._n_pubs = n_pubs

            def job_id(self):
                return "fakejob"

            def result(self):
                return [_FakePubResult() for _ in range(self._n_pubs)]

        class _FakeSampler:
            def run(self, pubs, shots):
                self.pubs = pubs
                return _FakeJob(len(pubs))

        fake_sampler = _FakeSampler()
        hb = HardwareBackend(service=None, backend_name="fake_backend")
        monkeypatch.setattr(hb, "_sampler", lambda backend: fake_sampler)
        monkeypatch.setattr(
            hb,
            "_backend",
            lambda: SimpleNamespace(name="fake_backend", target=SimpleNamespace(dt=1e-9)),
        )

        config = _base_config(p_list=[])
        tau_values = [0, 100, 200, 300]

        hb.run_tau_sweep(config, tau_values)

        assert call_counts["pm_run"] == 1
        assert len(fake_sampler.pubs) == len(tau_values)


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


@pytest.mark.parametrize("config_n,config_seed,backend_n,backend_seed,expected", [
    (None, None, 7, 314, (7, 314)), (11, 8, 7, 314, (11, 8)),
])
def test_sampling_effective_configuration(monkeypatch, config_n, config_seed, backend_n, backend_seed, expected):
    calls = []
    def runner(**kwargs):
        calls.append(kwargs)
        return [1.0], np.array([1, 0]), None
    monkeypatch.setattr("broadcasting.backend.run_broadcast_qec", runner)
    result = SamplingBackend(backend_n, backend_seed).run(_base_config(
        N=1, use_qec=True, n_samples=config_n, seed=config_seed))
    assert {(call["n_samples"], call["seed"]) for call in calls} == {expected}
    assert (result.metadata["n_samples"], result.metadata["seed"]) == expected


@pytest.mark.parametrize("taus", [[], [0, 0], [-1], [1.1], [float("nan")], [float("inf")], [None], [True]])
def test_invalid_hardware_delays_fail_before_backend_lookup(taus, monkeypatch):
    backend = HardwareBackend(None)
    monkeypatch.setattr(backend, "_backend", lambda: pytest.fail("Should not access hardware"))
    with pytest.raises(ValueError, match="tau"):
        backend.run_tau_sweep(_base_config(), taus)


def test_sender_counts_and_aligned_registers_with_local_sampler(monkeypatch, tmp_path):
    import base64
    import io
    from qiskit import qpy
    from qiskit_aer import AerSimulator
    from qiskit_aer.primitives import SamplerV2
    from broadcasting.results import save_run, load_run

    backend = HardwareBackend(None, shots=64, optimization_level=0)
    sampler = SamplerV2(seed=4)
    monkeypatch.setattr(backend, "_backend", lambda: AerSimulator())
    monkeypatch.setattr(backend, "_sampler", lambda ignored: sampler)
    config = _base_config(N=1, thetas=[0.3], p_list=[])
    result = backend.run(config)
    assert result.metadata["tau"] == 0
    assert result.metadata["sender_counts"] is not None
    assert result.metadata["invalid_sender_rate"] == 0
    aligned = result.metadata["aligned_shots"]
    assert aligned["num_shots"] == 64
    assert set(aligned["registers"]) == {"m", "fid"}
    assert set(aligned["registers"]["fid"]) == {"0"}
    templates = result.metadata["compiled_templates"]
    replay = qpy.load(io.BytesIO(base64.b64decode(templates[0]["qpy_base64"])))[0]
    replay = replay.assign_parameters({next(iter(replay.parameters)): 0})
    assert not replay.parameters
    saved = load_run(save_run(result, config, results_dir=tmp_path))
    assert saved["metadata"]["aligned_shots"] == aligned
    assert saved["outcomes_list"] is None
    assert saved["metadata"]["requested_outcomes_list"] == [0]


def test_fake_brisbane_bound_delay_fallback(monkeypatch):
    from qiskit_ibm_runtime.fake_provider import FakeBrisbane
    from qiskit.primitives.containers import BitArray, DataBin, SamplerPubResult
    class Job:
        def job_id(self): return "offline"
        def result(self):
            return [SamplerPubResult(DataBin(fid=BitArray.from_samples(["0"] * 4),
                                              m=BitArray.from_samples(["0"] * 4))) for _ in range(2)]
    class Sampler:
        def run(self, pubs, shots):
            assert all(not pub[0].parameters for pub in pubs)
            return Job()
    backend = HardwareBackend(None, shots=4, optimization_level=1)
    monkeypatch.setattr(backend, "_backend", FakeBrisbane)
    monkeypatch.setattr(backend, "_sampler", lambda _: Sampler())
    result = backend.run_tau_sweep(_base_config(N=1), [0, 104])
    assert result.metadata["compilation"][0]["mode"] == "bound per delay"
    assert len(result.metadata["compiled_templates"]) == 2
    assert result.metadata["calibration"]["dt_seconds"] > 0
    with pytest.raises(ValueError, match="multiples of 8"):
        backend.run_tau_sweep(_base_config(N=1), [100])


def test_hpc_command_roundtrips_shell_and_preserves_nonuniform_points():
    import shlex
    config = _base_config(M=2, thetas=[0.1, 0.7], outcomes_list=[1, 0], p_list=[0, 0.1, 1])
    result = HPCBackend().run(config)
    assert shlex.split(result.metadata["command"]) == result.metadata["argv"]
    assert "P_LIST=0 0.1 1," in result.metadata["argv"][1]


@pytest.mark.parametrize("alpha", [0.5 + 0.5j, 1.01, -1.01, float("nan"), float("inf")])
@pytest.mark.parametrize("backend", [ExactBackend(), SamplingBackend(), HPCBackend(), HardwareBackend(None)])
def test_all_execution_backends_reject_invalid_real_amplitudes(alpha, backend):
    with pytest.raises(ValueError, match="alpha must be real"):
        backend.run(_base_config(alpha=alpha, use_qec=True))
