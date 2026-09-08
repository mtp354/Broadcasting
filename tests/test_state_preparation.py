"""Tests for state preparation functions."""

import numpy as np
import pytest
from math import ceil, log2

import broadcasting as db


# ---------------------------------------------------------------------------
# Bare (non-QEC) initial state
# ---------------------------------------------------------------------------

class TestBareStatevector:
    """Tests for _build_initial_statevector."""

    @pytest.mark.parametrize("M,N", [(1, 1), (1, 2), (2, 2), (2, 3)])
    def test_normalization(self, M, N, alpha):
        sv = db.build_initial_statevector(M, N, alpha)
        assert abs(np.linalg.norm(sv) - 1.0) < 1e-12

    @pytest.mark.parametrize("M,N", [(1, 1), (1, 2), (2, 2), (2, 3)])
    def test_dimension(self, M, N, alpha):
        nq = int(ceil(log2(N + 1)))
        expected_dim = 2 ** (M * nq + N)
        sv = db.build_initial_statevector(M, N, alpha)
        assert sv.size == expected_dim

    def test_known_values_M1_N1(self, alpha):
        """M=1, N=1: sender has 1 qubit, receiver has 1 qubit (2 qubits total).

        |Psi> = alpha*|0>_sender|1>_receiver + beta*|1>_sender|0>_receiver
        With alpha=beta=1/sqrt(2) and Qiskit little-endian (qubit 0 = LSB):
        - sender qubit = qubit 0, receiver qubit = qubit 1
        - |0>_s|1>_r = |10> in big-endian = index: r*2 + s = 1*2 + 0 = 2
        - |1>_s|0>_r = |01> in big-endian = index: r*2 + s = 0*2 + 1 = 1
        """
        sv = db.build_initial_statevector(1, 1, alpha)
        beta = np.sqrt(1 - abs(alpha) ** 2)
        # Normalize: the full state has coefficients alpha*C(1,k) and beta*C(1,1-k)
        norm = np.linalg.norm(sv)
        assert abs(norm - 1.0) < 1e-12
        # Check nonzero entries
        nonzero_indices = np.nonzero(np.abs(sv) > 1e-12)[0]
        assert set(nonzero_indices) == {1, 2}


# ---------------------------------------------------------------------------
# QEC-encoded initial state
# ---------------------------------------------------------------------------

class TestQECStatevector:
    """Tests for _build_initial_statevector_qec_513."""

    @pytest.mark.parametrize("M,N", [(1, 1), (1, 2)])
    def test_normalization(self, M, N, alpha):
        sv = db.build_initial_statevector_qec_513(M, N, alpha)
        assert abs(np.linalg.norm(sv) - 1.0) < 1e-12

    @pytest.mark.parametrize("M,N", [(1, 1), (1, 2)])
    def test_dimension(self, M, N, alpha):
        nq = int(ceil(log2(N + 1)))
        expected_dim = 2 ** (M * nq + 5 * N)
        sv = db.build_initial_statevector_qec_513(M, N, alpha)
        assert sv.size == expected_dim

    def test_qec_state_in_code_space_M1_N1(self, alpha, stabilizer_matrices):
        """For M=1, N=1: the receiver's 5-qubit block must be in the [[5,1,3]] code space.

        This means tracing out the sender qubit and checking that each
        stabilizer has expectation value +1 on the receiver subsystem.
        """
        sv = db.build_initial_statevector_qec_513(1, 1, alpha)
        # M=1, N=1: 1 sender qubit + 5 receiver qubits = 6 qubits total
        assert sv.size == 64

        # Reshape to tensor: axes are (q0_sender, q1_recv, q2_recv, q3_recv, q4_recv, q5_recv)
        # Using Fortran order to match Qiskit convention
        psi = sv.reshape((2,) * 6, order="F")

        for S in stabilizer_matrices:
            S_tensor = S.reshape((2,) * 10, order="F")  # 5 bra + 5 ket indices

            # Compute <psi| (I_sender x S_receiver) |psi>
            # Contract S with receiver indices and check expectation value
            # Simpler approach: compute expectation for each sender branch
            expectation = 0.0
            for s_val in range(2):
                branch = psi[s_val].reshape(-1, order="F")  # 5-qubit receiver state
                branch_norm_sq = np.vdot(branch, branch)
                if branch_norm_sq > 1e-14:
                    ev = np.real(np.vdot(branch, S @ branch))
                    expectation += ev
            # Should be +1 (the full state is normalized)
            assert abs(expectation - 1.0) < 1e-10, (
                f"Stabilizer expectation = {expectation}, expected +1"
            )

    def test_f_order_vs_c_order_differ_M1_N2(self, alpha):
        """For M=1, N=2: C-order and F-order reshapes produce DIFFERENT tensors.

        This documents that the order='F' fix in commit 139aad5 is necessary.
        The palindrome symmetry of the logical basis does NOT save us here.
        """
        logical = db.build_initial_statevector(1, 2, alpha)
        nq = int(ceil(log2(3)))  # N=2 -> nq=2
        n_sender_qubits = 1 * nq  # M=1
        total_bare_qubits = n_sender_qubits + 2

        tensor_c = logical.reshape((2,) * total_bare_qubits, order="C")
        tensor_f = logical.reshape((2,) * total_bare_qubits, order="F")

        assert not np.allclose(tensor_c, tensor_f), (
            "C-order and F-order reshapes should differ for bare state with N=2"
        )


class TestCrossRepresentationEquivalence:
    """Verifies exact isomorphism between the native-qudit representation
    in broadcasting.simulation and Qiskit's little-endian binary multi-qubit
    representation in broadcasting.state_preparation."""

    @pytest.mark.parametrize("M,N", [(1, 1), (1, 2), (2, 2)])
    @pytest.mark.parametrize("alpha_val", [0.3, 1 / np.sqrt(2), 0.85])
    def test_native_qudit_to_binary_qubit_embedding(self, M, N, alpha_val):
        from broadcasting.simulation import get_initial_state

        psi_sim = get_initial_state(M, N, alpha_val).data
        psi_circ = db.build_initial_statevector(M, N, alpha_val)
        nq = int(ceil(log2(N + 1)))

        dims_sim = [N + 1] * M + [2] * N
        sim_tensor = psi_sim.reshape(dims_sim)
        embedded = np.zeros_like(psi_circ)

        for idx in np.ndindex(*dims_sim):
            senders = idx[:M]
            receivers = idx[M:]
            amp = sim_tensor[idx]
            if abs(amp) == 0:
                continue
            bit_index = 0
            for j, s_val in enumerate(senders):
                for b in range(nq):
                    bit = (s_val >> b) & 1
                    bit_pos = j * nq + b
                    bit_index |= (bit << bit_pos)
            for ell, r_val in enumerate(receivers):
                bit_pos = M * nq + ell
                bit_index |= (r_val << bit_pos)
            embedded[bit_index] = amp

        overlap = abs(np.vdot(embedded, psi_circ))
        assert overlap == pytest.approx(1.0, abs=1e-10)
