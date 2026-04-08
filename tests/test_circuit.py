"""Circuit integration tests (require qiskit-aer)."""

import numpy as np
import pytest
from math import ceil, log2

import broadcasting as db

# Try importing Aer; skip these tests if unavailable.
aer = pytest.importorskip("qiskit_aer")
from qiskit_aer import AerSimulator


def _run_fidelity_statevector(M, N, thetas, use_qec=False):
    """Build circuit, add fidelity measurement, simulate, return per-receiver fidelities."""
    alpha = 1 / np.sqrt(2)
    qc = db.generate_qiskit_circuit(
        M, N, thetas, alphas=alpha, tau=0, use_receiver_qec_513=use_qec,
    )
    qc, reg_name, phi = db.add_fidelity(qc, N=N, thetas=thetas)

    sim = AerSimulator(method="automatic")
    result = sim.run(qc, shots=8192).result()
    counts = result.get_counts()

    # Extract per-receiver P(0) from the fidelity register.
    # Qiskit get_counts() bitstring format: "regN ... reg1 reg0" (space-separated).
    # The fidelity register is added last, so it appears leftmost.
    # Within each register, bits are big-endian: bit[0]=MSB.
    # For the fid register of size N: fid_bits[0] = receiver N-1, fid_bits[N-1] = receiver 0.
    fidelities = []
    total = sum(counts.values())
    for i in range(N):
        p0 = 0
        for bitstr, count in counts.items():
            fid_bits = bitstr.split()[0]
            if fid_bits[N - 1 - i] == "0":
                p0 += count
        fidelities.append(p0 / total)
    return fidelities


# ---------------------------------------------------------------------------
# Gate unit tests
# ---------------------------------------------------------------------------

class TestSenderPhaseGate:
    def test_diagonal_and_unitary(self):
        N, nq = 2, 2
        gate = db.sender_phase_gate(theta=0.5, N=N, nq=nq)
        U = gate.to_matrix()
        # Should be diagonal
        assert np.allclose(U, np.diag(np.diag(U)))
        # Should be unitary
        assert np.allclose(U @ U.conj().T, np.eye(2**nq), atol=1e-12)


class TestFourierRotation:
    def test_unitary(self):
        N, nq = 2, 2
        gate = db.fourier_measurement_rotation(N=N, nq=nq)
        U = gate.to_matrix()
        assert np.allclose(U @ U.conj().T, np.eye(2**nq), atol=1e-12)

    def test_top_left_block_is_fourier_dagger(self):
        N = 2
        nq = int(ceil(log2(N + 1)))
        gate = db.fourier_measurement_rotation(N=N, nq=nq)
        U = gate.to_matrix()
        d = N + 1
        omega = np.exp(2j * np.pi / d)
        F = np.array([[omega ** (n * k) / np.sqrt(d) for k in range(d)] for n in range(d)])
        assert np.allclose(U[:d, :d], F.conj().T, atol=1e-12)


# ---------------------------------------------------------------------------
# Non-QEC circuit fidelity
# ---------------------------------------------------------------------------

class TestNonQECFidelity:
    @pytest.mark.parametrize("M,N,thetas", [
        (1, 1, [0.3]),
        (1, 2, [0.3]),
        (2, 2, [0.3, 0.5]),
    ])
    def test_statevector_fidelity_near_one(self, M, N, thetas):
        fidelities = _run_fidelity_statevector(M, N, thetas, use_qec=False)
        for i, fid in enumerate(fidelities):
            assert fid > 0.99, (
                f"Non-QEC fidelity for receiver {i} = {fid:.4f}, expected > 0.99"
            )


# ---------------------------------------------------------------------------
# QEC circuit fidelity
# ---------------------------------------------------------------------------

class TestQECFidelity:
    def test_qec_fidelity_M1_N1(self):
        fidelities = _run_fidelity_statevector(1, 1, [0.3], use_qec=True)
        for i, fid in enumerate(fidelities):
            assert fid > 0.99, (
                f"QEC fidelity for receiver {i} = {fid:.4f}, expected > 0.99"
            )

    @pytest.mark.slow
    def test_qec_fidelity_M1_N2(self):
        fidelities = _run_fidelity_statevector(1, 2, [0.3], use_qec=True)
        for i, fid in enumerate(fidelities):
            assert fid > 0.99, (
                f"QEC fidelity for receiver {i} = {fid:.4f}, expected > 0.99"
            )


# ---------------------------------------------------------------------------
# Circuit metadata
# ---------------------------------------------------------------------------

class TestCircuitMetadata:
    def test_receiver_output_qubits_non_qec(self):
        qc = db.generate_qiskit_circuit(1, 2, [0.3], tau=0)
        meta = qc.metadata or {}
        qubits = meta.get("receiver_output_qubits", [])
        assert len(qubits) == 2

    def test_receiver_output_qubits_qec(self):
        qc = db.generate_qiskit_circuit(1, 1, [0.3], tau=0, use_receiver_qec_513=True)
        meta = qc.metadata or {}
        qubits = meta.get("receiver_output_qubits", [])
        assert len(qubits) == 1

    def test_add_fidelity_register_naming(self):
        qc = db.generate_qiskit_circuit(1, 2, [0.3], tau=0)
        qc, reg_name, phi = db.add_fidelity(qc, N=2, thetas=[0.3])
        assert reg_name == "fid"
        fid_reg = next(r for r in qc.cregs if r.name == reg_name)
        assert fid_reg.size == 2
