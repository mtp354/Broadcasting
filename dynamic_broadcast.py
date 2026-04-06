import itertools
from math import ceil, log2

import numpy as np
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit.library import UnitaryGate


def _sender_encoding_qubits(N: int) -> int:
    """Number of qubits needed to embed one (N+1)-level sender qudit."""
    return int(ceil(log2(N + 1)))


def _packed_sender_value(outcomes, nq):
    """Pack sender outcomes into a single little-endian classical integer."""
    packed = 0
    for j, outcome in enumerate(outcomes):
        for bit in range(nq):
            packed |= ((outcome >> bit) & 1) << (j * nq + bit)
    return packed


def _build_initial_statevector(M: int, N: int, alpha: complex) -> np.ndarray:
    """
    Build |Psi^(M,N)> embedded into qubits.

    Sender qudits (dimension N+1) are encoded in nq=ceil(log2(N+1)) qubits each,
    and receiver qubits are appended after sender qubits.
    """
    nq = _sender_encoding_qubits(N)
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


def _sender_phase_gate(theta: float, N: int, nq: int) -> UnitaryGate:
    """Diagonal gate implementing U_a(theta)|k> = exp(i(2k-N)theta)|k> for k=0..N."""
    dim = 2**nq
    diag = np.ones(dim, dtype=complex)
    for k in range(N + 1):
        diag[k] = np.exp(1j * (2 * k - N) * theta)
    return UnitaryGate(np.diag(diag), label=f"Ua({theta:.3f})")


def _fourier_measurement_rotation(N: int, nq: int) -> UnitaryGate:
    r"""
    Unitary whose top-left block is F_d^\dagger (d=N+1), identity elsewhere.

    Applying this then computational-basis measurement reproduces a Fourier-basis
    measurement on the sender qudit subspace.
    """
    d = N + 1
    dim = 2**nq
    omega = np.exp(2j * np.pi / d)

    F = np.zeros((d, d), dtype=complex)
    for n in range(d):
        for k in range(d):
            F[n, k] = omega ** (n * k) / np.sqrt(d)

    U = np.eye(dim, dtype=complex)
    U[:d, :d] = F.conj().T
    return UnitaryGate(U, label="Fdg")


def generate_qiskit_circuit(M, N, thetas, alphas=1 / np.sqrt(2)):
    """
    Construct a dynamic Qiskit circuit for the M-sender, N-receiver protocol.

    The circuit performs:
    1) shared resource-state preparation |Psi^(M,N)>,
    2) sender local phase unitaries from `thetas`,
    3) sender Fourier-basis measurements,
    4) classical feedforward correction on receiver qubits.

    Parameters
    ----------
    M : int
        Number of senders.
    N : int
        Number of receivers.
    thetas : sequence of float
        Length-M list/array of sender angles.
    alphas : complex, optional
        Alpha parameter from the protocol (default 1/sqrt(2)).

    Returns
    -------
    QuantumCircuit
        Dynamic circuit implementing protocol control flow.
    """
    if len(thetas) != M:
        raise ValueError(f"Expected {M} theta values, got {len(thetas)}.")

    nq = _sender_encoding_qubits(N)
    n_sender_qubits = M * nq

    senders = QuantumRegister(n_sender_qubits, "a")
    receivers = QuantumRegister(N, "r")
    c_senders = ClassicalRegister(n_sender_qubits, "m")
    qc = QuantumCircuit(senders, receivers, c_senders, name="MN_broadcast")

    init_state = _build_initial_statevector(M=M, N=N, alpha=alphas)
    qc.initialize(init_state, list(senders) + list(receivers)) # type: ignore

    for j, theta in enumerate(thetas):
        qslice = [senders[j * nq + b] for b in range(nq)]
        qc.append(_sender_phase_gate(theta=float(theta), N=N, nq=nq), qslice)

    Fdg = _fourier_measurement_rotation(N=N, nq=nq)
    for j in range(M):
        qslice = [senders[j * nq + b] for b in range(nq)]
        cslice = [c_senders[j * nq + b] for b in range(nq)]
        qc.append(Fdg, qslice)
        qc.measure(qslice, cslice)

    d = N + 1
    for outcomes in itertools.product(range(d), repeat=M):
        phase = 2 * np.pi * (sum(outcomes) % d) / d
        packed = _packed_sender_value(outcomes, nq)

        with qc.if_test((c_senders, packed)):
            for qb in receivers:
                qc.p(phase, qb)

    return qc
