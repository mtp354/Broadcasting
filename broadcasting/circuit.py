"""Sender gates and main circuit generation for the broadcasting protocol."""

import itertools

import numpy as np
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit import Parameter
from qiskit.circuit.library import UnitaryGate

from .helpers import packed_sender_value, sender_encoding_qubits
from .qec_513 import decode_qec_513
from .state_preparation import build_initial_statevector, build_initial_statevector_qec_513


def sender_phase_gate(theta: float, N: int, nq: int) -> UnitaryGate:
    """Diagonal gate implementing U_a(theta)|k> = exp(i(2k-N)theta)|k> for k=0..N."""
    dim = 2**nq
    diag = np.ones(dim, dtype=complex)
    for k in range(N + 1):
        diag[k] = np.exp(1j * (2 * k - N) * theta)
    return UnitaryGate(np.diag(diag), label=f"Ua({theta:.3f})")


def fourier_measurement_rotation(N: int, nq: int) -> UnitaryGate:
    r"""
    Unitary whose top-left block is F_d^\dagger (d=N+1), identity elsewhere.

    Applying this then computational-basis measurement reproduces a Fourier-basis
    measurement on the sender qudit subspace.
    """
    d = N + 1
    dim = 2**nq
    omega = np.exp(2j * np.pi / d)

    indices = np.arange(d)
    fourier = omega ** np.outer(indices, indices) / np.sqrt(d)
    rotation = np.eye(dim, dtype=complex)
    rotation[:d, :d] = fourier.conj().T
    return UnitaryGate(rotation, label="Fdg")


def generate_qiskit_circuit(
    M,
    N,
    thetas,
    alphas=1 / np.sqrt(2),
    tau=None,
    delay_unit="dt",
    use_receiver_qec_513=False,
    linear_feedforward=True,
    receiver_delay_factors=None,
):
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
    tau : float | Parameter | None, optional
        Delay duration inserted after state preparation and before sender
        unitaries. If None, the circuit is created with a symbolic parameter
        `tau` so it can be swept over a range of values.
    delay_unit : str, optional
        Unit used by Qiskit's delay instruction (default "dt").
    receiver_delay_factors : sequence of int | None, optional
        Nonnegative multipliers of tau for each logical receiver. Defaults to
        one for every receiver. For example, [1, 0] delays only receiver zero.
        With QEC, the multiplier applies to all five physical block qubits.
    use_receiver_qec_513 : bool, optional
        If True, encode each receiver qubit into a [[5,1,3]] block.
    linear_feedforward : bool, optional
        If True (default), implement the byproduct correction with
        ``M * nq`` single-bit-conditioned phase rotations instead of the
        ``(N+1)**M``-branch exponential feedforward. Mathematically identical
        for every *valid* sender outcome (phase corrections add linearly bit by
        bit); for an *invalid* outcome (register value > N, only possible when
        N+1 is not a power of two) it applies the same linear phase formula
        rather than skipping correction. Set False to enumerate only valid
        outcomes and apply no correction for invalid register values.

    Returns
    -------
    QuantumCircuit
        Dynamic circuit implementing protocol control flow.
    """
    if len(thetas) != M:
        raise ValueError(f"Expected {M} theta values, got {len(thetas)}.")
    delay_factors = [1] * N if receiver_delay_factors is None else list(receiver_delay_factors)
    if len(delay_factors) != N or any(
        isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0
        for value in delay_factors
    ) or not any(delay_factors):
        raise ValueError("receiver_delay_factors must contain N nonnegative integers, at least one positive.")

    nq = sender_encoding_qubits(N)
    n_sender_qubits = M * nq
    n_receiver_physical = 5 * N if use_receiver_qec_513 else N

    senders = QuantumRegister(n_sender_qubits, "a")
    receivers = QuantumRegister(n_receiver_physical, "r")
    c_senders = ClassicalRegister(n_sender_qubits, "m")
    qc = QuantumCircuit(senders, receivers, c_senders, name="MN_broadcast")

    init_state = (
        build_initial_statevector_qec_513(M=M, N=N, alpha=alphas)
        if use_receiver_qec_513
        else build_initial_statevector(M=M, N=N, alpha=alphas)
    )
    qc.initialize(init_state, list(senders) + list(receivers))  # type: ignore

    tau_param = Parameter("tau") if tau is None else tau
    for index, qb in enumerate(receivers):
        receiver_index = index // 5 if use_receiver_qec_513 else index
        factor = delay_factors[receiver_index]
        qc.delay(tau_param * factor if factor else 0, qb, unit=delay_unit)

    active_receivers = list(receivers)
    if use_receiver_qec_513:
        encoded_blocks = [
            [receivers[5 * ell + t] for t in range(5)] for ell in range(N)
        ]
        output_indices = decode_qec_513(qc, encoded_blocks)
        active_receivers = [qc.qubits[idx] for idx in output_indices]
    qc.metadata = qc.metadata or {}
    qc.metadata["receiver_output_qubits"] = [qc.find_bit(qb).index for qb in active_receivers]

    for j, theta in enumerate(thetas):
        qslice = [senders[j * nq + b] for b in range(nq)]
        qc.append(sender_phase_gate(theta=float(theta), N=N, nq=nq), qslice)

    fourier_rotation = fourier_measurement_rotation(N=N, nq=nq)
    for j in range(M):
        qslice = [senders[j * nq + b] for b in range(nq)]
        cslice = [c_senders[j * nq + b] for b in range(nq)]
        qc.append(fourier_rotation, qslice)
        qc.measure(qslice, cslice)

    d = N + 1
    if linear_feedforward:
        # phase(sum_j n_j) = 2*pi/(N+1) * sum_j n_j is periodic in (N+1), so it
        # decomposes additively over senders *and* over each sender's bits:
        # sum_j n_j = sum_{j,b} bit_{j,b} * 2**b. Each bit contributes an
        # independent, single-bit-conditioned phase rotation -- M*nq branches
        # total instead of (N+1)**M.
        for j in range(M):
            for b in range(nq):
                phase = 2 * np.pi * (1 << b) / d
                with qc.if_test((c_senders[j * nq + b], 1)):
                    for qb in active_receivers:
                        qc.p(-phase, qb)
    else:
        for outcomes in itertools.product(range(d), repeat=M):
            phase = 2 * np.pi * (sum(outcomes) % d) / d
            packed = packed_sender_value(outcomes, nq)

            with qc.if_test((c_senders, packed)):
                for qb in active_receivers:
                    qc.p(-phase, qb)

    return qc
