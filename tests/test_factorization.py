"""Check the manuscript's full-joint theorem, including non-depolarizing noise."""

import itertools
from functools import reduce

import numpy as np
import pytest
from qiskit.quantum_info import DensityMatrix

from broadcasting.simulation import (
    apply_alice_unitaries,
    apply_corrections,
    depolarizing_channels,
    get_initial_state,
    measure_alices,
    partial_trace_np,
)


def _kron_all(operators):
    return reduce(np.kron, operators)


def _amplitude_damping(rho, gamma):
    k0 = np.diag([1.0, np.sqrt(1.0 - gamma)])
    k1 = np.array([[0.0, np.sqrt(gamma)], [0.0, 0.0]])
    return sum(k @ rho @ k.conj().T for k in (k0, k1))


@pytest.mark.parametrize("M,N,alpha", [(1, 3, 0.37), (2, 2, -0.61), (3, 1, 0.3 + 0.4j)])
@pytest.mark.parametrize("channel", ["depolarizing", "amplitude_damping"])
def test_all_sender_branches_factorize_with_nonuniform_covariant_noise(M, N, alpha, channel):
    """Every branch has uniform probability and the predicted complete joint state.

    The amplitude-damping case checks the phase-covariant generalization, rather
    than only the isotropic channel for which local fidelities already had tests.
    Nonuniform channel strengths also make receiver ordering observable.
    """
    d = N + 1
    angles = [0.23 + 0.17 * j for j in range(M)]
    strengths = np.linspace(0.09, 1.0, N) if N > 1 else np.array([0.84])
    rho = DensityMatrix(get_initial_state(M, N, alpha))

    if channel == "depolarizing":
        rho = depolarizing_channels(M, N, rho, strengths.tolist())
    else:
        # Independent Kraus construction, with the sender register untouched.
        for ell, gamma in enumerate(strengths):
            local = (np.diag([1.0, np.sqrt(1 - gamma)]),
                     np.array([[0.0, np.sqrt(gamma)], [0.0, 0.0]]))
            operators = [np.kron(np.eye(d**M * 2**ell),
                                np.kron(k, np.eye(2**(N - ell - 1)))) for k in local]
            rho = DensityMatrix(sum(k @ rho.data @ k.conj().T for k in operators))

    phased = apply_alice_unitaries(M, N, rho, angles)
    phi = sum(angles)
    target = np.array([alpha * np.exp(1j * phi),
                       np.sqrt(1 - abs(alpha)**2) * np.exp(-1j * phi)])
    pure = np.outer(target, target.conj())
    if channel == "depolarizing":
        expected_local = [(1 - 4 * p / 3) * pure + 2 * p / 3 * np.eye(2)
                          for p in strengths]
    else:
        expected_local = [_amplitude_damping(pure, gamma) for gamma in strengths]
    expected_joint = _kron_all(expected_local)
    target_joint = _kron_all([target] * N)
    product_fidelity = np.prod([np.vdot(target, local @ target).real
                                for local in expected_local])

    for outcomes in itertools.product(range(d), repeat=M):
        fourier_kets = [np.exp(2j * np.pi * n * np.arange(d) / d) / np.sqrt(d)
                       for n in outcomes]
        sender_ket = _kron_all(fourier_kets)
        branch_bra = np.kron(sender_ket.conj().reshape(1, -1), np.eye(2**N))
        unnormalized = branch_bra @ phased.data @ branch_bra.conj().T
        assert np.trace(unnormalized).real == pytest.approx(d**(-M), abs=2e-12)

        measured, actual_outcomes = measure_alices(M, N, phased, list(outcomes))
        corrected = apply_corrections(M, N, measured, actual_outcomes)
        joint = partial_trace_np(corrected, (d**M, 2**N), [1])
        np.testing.assert_allclose(joint, expected_joint, atol=2e-12)
        assert np.vdot(target_joint, joint @ target_joint).real == pytest.approx(
            product_fidelity, abs=2e-12
        )
