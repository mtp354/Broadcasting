"""Validate the structured resource-state prep and linear feedforward against
the existing (already-tested) generic implementations, before any hardware use.
"""

import numpy as np
import pytest
from math import ceil, log2

import broadcasting as db
from broadcasting.circuit import structured_state_prep

aer = pytest.importorskip("qiskit_aer")
from qiskit.quantum_info import Statevector
from qiskit import QuantumCircuit, QuantumRegister
from qiskit_aer import AerSimulator


def _structured_statevector(M, N, alpha):
    nq = int(ceil(log2(N + 1)))
    senders = QuantumRegister(M * nq, "a")
    receivers = QuantumRegister(N, "r")
    qc = QuantumCircuit(senders, receivers)
    structured_state_prep(qc, list(senders), list(receivers), M, N, nq, alpha)
    return Statevector(qc).data


class TestStructuredStatePrep:
    """structured_state_prep must reproduce build_initial_statevector exactly."""

    @pytest.mark.parametrize("M,N", [(1, 1), (2, 1), (3, 1), (1, 2), (2, 2), (3, 2)])
    @pytest.mark.parametrize("alpha", [1 / np.sqrt(2), 0.3, 0.8, 0.0, 1.0])
    def test_matches_reference(self, M, N, alpha):
        expected = db.build_initial_statevector(M, N, alpha)
        actual = _structured_statevector(M, N, alpha)
        # Global phase is physically irrelevant; compare up to phase.
        overlap = np.vdot(expected, actual)
        assert abs(overlap) == pytest.approx(1.0, abs=1e-9)
        phase = overlap / abs(overlap) if abs(overlap) > 0 else 1.0
        assert np.allclose(actual, phase * expected, atol=1e-9)

    def test_rejects_unimplemented_N(self):
        with pytest.raises(NotImplementedError):
            _structured_statevector(1, 3, 1 / np.sqrt(2))


class TestLinearFeedforward:
    """linear_feedforward=True must reproduce linear_feedforward=False's fidelity
    for every valid sender outcome, using ordinary qc.initialize-based prep."""

    @pytest.mark.parametrize("M,N,thetas", [
        (1, 1, [0.3]),
        (1, 2, [0.7]),
        (2, 2, [0.3, 1.1]),
    ])
    def test_matches_exponential_feedforward(self, M, N, thetas):
        def run(linear):
            qc = db.generate_qiskit_circuit(
                M, N, thetas, alphas=1 / np.sqrt(2), tau=0,
                linear_feedforward=linear,
            )
            qc, reg_name, _ = db.add_fidelity(qc, N=N, thetas=thetas)
            sim = AerSimulator(method="automatic")
            result = sim.run(qc, shots=8192, seed_simulator=0).result()
            counts = result.get_counts()
            total = sum(counts.values())
            fids = []
            for i in range(N):
                p0 = sum(
                    c for bs, c in counts.items()
                    if bs.split()[0][N - 1 - i] == "0"
                )
                fids.append(p0 / total)
            return fids

        fid_linear = run(True)
        fid_exp = run(False)
        for a, b in zip(fid_linear, fid_exp):
            assert a == pytest.approx(b, abs=0.03)

    def test_structured_prep_plus_linear_feedforward_end_to_end(self):
        """Full structured-circuit path should also give near-unit fidelity."""
        M, N, thetas = 1, 2, [0.4]
        qc = db.generate_qiskit_circuit(
            M, N, thetas, alphas=1 / np.sqrt(2), tau=0,
            use_structured_prep=True, linear_feedforward=True,
        )
        qc, reg_name, _ = db.add_fidelity(qc, N=N, thetas=thetas, alpha=1 / np.sqrt(2))
        sim = AerSimulator(method="automatic")
        result = sim.run(qc, shots=8192, seed_simulator=0).result()
        counts = result.get_counts()
        total = sum(counts.values())
        for i in range(N):
            p0 = sum(
                c for bs, c in counts.items()
                if bs.split()[0][N - 1 - i] == "0"
            )
            assert p0 / total > 0.99
