"""State vector preparation for the broadcasting protocol."""

import itertools

import numpy as np

from .helpers import sender_encoding_qubits
from .qec_513 import five_qubit_logical_basis


def build_initial_statevector(M: int, N: int, alpha: complex) -> np.ndarray:
    """
    Build |Psi^(M,N)> embedded into qubits.

    Sender qudits (dimension N+1) are encoded in nq=ceil(log2(N+1)) qubits each,
    and receiver qubits are appended after sender qubits.
    """
    nq = sender_encoding_qubits(N)
    n_sender_qubits = M * nq
    n_total_qubits = n_sender_qubits + N
    dim = 2**n_total_qubits

    beta = np.sqrt(1 - abs(alpha) ** 2)
    state = np.zeros(dim, dtype=complex)

    for k in range(N + 1):
        amp = (alpha**k) * (beta ** (N - k))

        sender_bits = 0
        for j in range(M):
            sender_bits |= (k << (j * nq))

        for zeros in itertools.combinations(range(N), k):
            receiver_bits = (1 << N) - 1
            for z in zeros:
                receiver_bits &= ~(1 << z)

            basis_index = sender_bits | (receiver_bits << n_sender_qubits)
            state[basis_index] += amp

    norm = np.linalg.norm(state)
    if norm == 0:
        raise ValueError("Constructed zero state; check parameters.")
    return state / norm


def build_initial_statevector_qec_513(M: int, N: int, alpha: complex) -> np.ndarray:
    """
    Build |Psi^(M,N)> with each receiver qubit encoded into a [[5,1,3]] block.

    Important ordering convention (matches generate_qiskit_circuit):
    - Sender *qubits* stay unchanged and remain first.
    - Receiver logical qubits are encoded one-by-one into 5 physical qubits.

    All reshapes use order='F' (Fortran/column-major) to match Qiskit's
    little-endian convention where qubit 0 (axis 0 in the tensor) is the LSB.
    """
    logical = build_initial_statevector(M=M, N=N, alpha=alpha)
    v0, v1 = five_qubit_logical_basis()
    nq = sender_encoding_qubits(N)
    n_sender_qubits = M * nq

    expected_dim = 2 ** (n_sender_qubits + N)
    if logical.size != expected_dim:
        raise ValueError(
            f"Logical state dimension mismatch: got {logical.size}, expected {expected_dim}."
        )

    # Encoding tensor E[b1,b2,b3,b4,b5,q], where q is one logical receiver qubit.
    # Use Fortran order so that axis j corresponds to qubit j (bit j of the
    # state-vector index), matching Qiskit's little-endian convention.
    E = np.zeros((2, 2, 2, 2, 2, 2), dtype=complex)
    E[..., 0] = v0.reshape(2, 2, 2, 2, 2, order="F")
    E[..., 1] = v1.reshape(2, 2, 2, 2, 2, order="F")

    # Tensor axes: sender qubits first, then receiver logical qubits.
    # Fortran order ensures axis j = qubit j (little-endian).
    psi = logical.reshape((2,) * (n_sender_qubits + N), order="F")

    # Encode receiver qubits left-to-right, preserving sender qubits exactly.
    for ell in range(N):
        ax = n_sender_qubits + 5 * ell
        R = psi.ndim
        psi = np.tensordot(E, psi, axes=([5], [ax]))
        perm = list(range(5, 5 + ax)) + list(range(0, 5)) + list(range(5 + ax, 5 + (R - 1)))
        psi = np.transpose(psi, perm)

    encoded = psi.reshape(-1, order="F")
    expected_encoded_dim = 2 ** (n_sender_qubits + 5 * N)
    if encoded.size != expected_encoded_dim:
        raise RuntimeError(
            f"Encoded state dimension mismatch: got {encoded.size}, expected {expected_encoded_dim}."
        )

    return encoded / np.linalg.norm(encoded)
