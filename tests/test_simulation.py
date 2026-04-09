"""Tests for broadcasting.simulation — local density-matrix simulations."""

import numpy as np
import pytest

from qiskit.quantum_info import DensityMatrix

from broadcasting.simulation import (
    get_initial_state,
    depolarizing_channels,
    apply_alice_unitaries,
    measure_alices,
    apply_corrections,
    run_broadcast_no_qec,
    run_broadcast_qec,
    partial_trace_np,
)


class TestInitialState:
    """get_initial_state should return a normalized Statevector of correct dimension."""

    @pytest.mark.parametrize("M, N", [(1, 2), (2, 2), (1, 3)])
    def test_dimension(self, M, N):
        alpha = 1 / np.sqrt(N + 1)
        sv = get_initial_state(M, N, alpha)
        dim = (N + 1) ** M * (2 ** N)
        assert sv.data.shape == (dim,)

    @pytest.mark.parametrize("M, N", [(1, 2), (2, 2)])
    def test_normalization(self, M, N):
        alpha = 1 / np.sqrt(N + 1)
        sv = get_initial_state(M, N, alpha)
        assert np.isclose(np.sum(np.abs(sv.data) ** 2), 1.0)


class TestPartialTrace:
    """partial_trace_np should preserve trace and positivity."""

    def test_trace_preserved(self):
        rho = np.eye(6, dtype=complex) / 6
        rho_red = partial_trace_np(DensityMatrix(rho), dims=[2, 3], keep=[0])
        assert np.isclose(np.trace(rho_red), 1.0)

    def test_positive_semidefinite(self):
        rho = np.eye(6, dtype=complex) / 6
        rho_red = partial_trace_np(DensityMatrix(rho), dims=[2, 3], keep=[1])
        eigvals = np.linalg.eigvalsh(rho_red)
        assert np.all(eigvals >= -1e-12)


class TestNoQECPipeline:
    """End-to-end no-QEC simulation at p=0 should give perfect fidelity."""

    def test_perfect_fidelity_at_zero_noise(self):
        M, N = 1, 2
        alpha = 1 / np.sqrt(N + 1)
        thetas = [np.pi / 4]
        fidelities, _, _ = run_broadcast_no_qec(
            M, N, alpha, thetas, p_list=[0.0] * N, outcomes_list=[0]
        )
        for f in fidelities:
            assert f > 0.99, f"Expected near-perfect fidelity, got {f}"

    def test_fidelity_degrades_with_noise(self):
        M, N = 1, 2
        alpha = 1 / np.sqrt(N + 1)
        thetas = [np.pi / 4]
        fid_clean, _, _ = run_broadcast_no_qec(
            M, N, alpha, thetas, p_list=[0.0] * N, outcomes_list=[0]
        )
        fid_noisy, _, _ = run_broadcast_no_qec(
            M, N, alpha, thetas, p_list=[0.5] * N, outcomes_list=[0]
        )
        # At least one receiver should have lower fidelity at p=0.5
        assert min(fid_noisy) < min(fid_clean)


class TestQECPipeline:
    """End-to-end QEC simulation."""

    def test_exact_perfect_fidelity_at_zero_noise(self):
        M, N = 1, 2
        alpha = 1 / np.sqrt(N + 1)
        thetas = [np.pi / 4]
        fidelities, _, _ = run_broadcast_qec(
            M, N, alpha, thetas, p_list=[0.0] * N,
            outcomes_list=[0], mode="exact",
        )
        for f in fidelities:
            assert f > 0.99, f"Expected near-perfect fidelity, got {f}"

    def test_sampling_perfect_fidelity_at_zero_noise(self):
        M, N = 1, 2
        alpha = 1 / np.sqrt(N + 1)
        thetas = [np.pi / 4]
        fidelities, _, _ = run_broadcast_qec(
            M, N, alpha, thetas, p_list=[0.0] * N,
            outcomes_list=[0], mode="sampling", n_samples=500, seed=0,
        )
        for f in fidelities:
            assert f > 0.99, f"Expected near-perfect fidelity, got {f}"

    def test_exact_vs_sampling_close(self):
        """At moderate noise, exact and sampling should roughly agree."""
        M, N = 1, 2
        alpha = 1 / np.sqrt(N + 1)
        thetas = [np.pi / 4]
        fid_exact, _, _ = run_broadcast_qec(
            M, N, alpha, thetas, p_list=[0.3] * N,
            outcomes_list=[0], mode="exact",
        )
        fid_samp, _, _ = run_broadcast_qec(
            M, N, alpha, thetas, p_list=[0.3] * N,
            outcomes_list=[0], mode="sampling", n_samples=5000, seed=42,
        )
        for fe, fs in zip(fid_exact, fid_samp):
            assert abs(fe - fs) < 0.1, (
                f"Exact ({fe:.4f}) and sampling ({fs:.4f}) diverge too much"
            )
