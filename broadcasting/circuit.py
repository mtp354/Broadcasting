"""Sender gates and main circuit generation for the broadcasting protocol."""

import itertools

import numpy as np
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit import Parameter
from qiskit.circuit.library import UnitaryGate

from .helpers import sender_encoding_qubits, packed_sender_value
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

    F = np.zeros((d, d), dtype=complex)
    for n in range(d):
        for k in range(d):
            F[n, k] = omega ** (n * k) / np.sqrt(d)

    U = np.eye(dim, dtype=complex)
    U[:d, :d] = F.conj().T
    return UnitaryGate(U, label="Fdg")


def structured_state_prep(qc, senders, receivers, M, N, nq, alpha):
    r"""Append a structured (non-generic-isometry) preparation of ``|Psi^(M,N)>``.

    Replaces Qiskit's generic ``qc.initialize`` (which synthesizes an arbitrary
    isometry and can require dozens of CNOTs even for small ``M, N``) with an
    explicit circuit exploiting the resource state's structure. Currently
    implemented for ``N in {1, 2}`` — the cases used throughout the manuscript's
    hardware experiments; larger ``N`` falls back to ``qc.initialize`` in
    :func:`generate_qiskit_circuit`.

    Convention (matches :func:`broadcasting.state_preparation.build_initial_statevector`
    exactly): sender qudit value ``k`` equals the number of receiver qubits equal
    to ``|0>`` (i.e. ``k = N - popcount(receiver_bits)``), *not* a generic Hamming
    weight of ``|1>`` bits.

    Construction, for real ``alpha`` with ``0 <= alpha <= 1``:

    1. Prepare each receiver qubit independently as ``alpha|0> + beta|1>`` via
       ``Ry(2*arccos(alpha))``. Expanding the resulting product state directly
       reproduces the correct amplitude for every receiver computational-basis
       string (no entanglement needed at this stage).
    2. Coherently compute ``k`` (as an ``nq``-bit binary number) into sender 0's
       register from the receiver qubits:

       - ``N=1``: ``nq=1`` and ``k = NOT(receiver bit)`` directly.
       - ``N=2``: ``nq=2``; using ``z_i = NOT(receiver_i)``, the sum
         ``k = z_0 + z_1`` is computed via a half adder. The sum (LSB) bit
         equals ``receiver_0 XOR receiver_1`` (the NOT cancels out of an XOR),
         so no inversion is needed there; the carry (MSB) bit is
         ``NOT(receiver_0) AND NOT(receiver_1)``, computed with an
         anti-controlled Toffoli (X-sandwiched ``ccx``).
    3. Copy sender 0's ``nq``-bit register into every other sender's register
       with ``nq`` CNOTs per sender (all senders must observe the identical
       value ``k``).

    Parameters
    ----------
    qc : QuantumCircuit
        Circuit to modify **in place**. Assumed freshly created (all qubits
        in ``|0>``) before this call.
    senders : Sequence[Qubit]
        All sender qubits, ordered ``[sender0_bit0, sender0_bit1, ..., sender1_bit0, ...]``.
    receivers : Sequence[Qubit]
        The ``N`` receiver qubits.
    M, N, nq : int
        Protocol sizes; ``nq`` must equal ``ceil(log2(N+1))``.
    alpha : float
        Real amplitude parameter, ``0 <= alpha <= 1``.

    Raises
    ------
    NotImplementedError
        If ``N`` is not 1 or 2.
    """
    if N not in (1, 2):
        raise NotImplementedError(
            f"structured_state_prep is only implemented for N in {{1, 2}}; got N={N}. "
            "Use generate_qiskit_circuit(..., use_structured_prep=False) to fall back "
            "to qc.initialize for larger N."
        )

    alpha = float(np.real(alpha))
    theta = 2.0 * np.arccos(np.clip(alpha, -1.0, 1.0))
    for r in receivers:
        qc.ry(theta, r)

    if N == 1:
        r0 = receivers[0]
        for j in range(M):
            k_bit = senders[j * nq]
            qc.x(k_bit)
            qc.cx(r0, k_bit)
        return

    # N == 2
    r0, r1 = receivers[0], receivers[1]
    sum_bit, carry_bit = senders[0], senders[1]

    qc.cx(r0, sum_bit)
    qc.cx(r1, sum_bit)

    qc.x(r0)
    qc.x(r1)
    qc.ccx(r0, r1, carry_bit)
    qc.x(r0)
    qc.x(r1)

    for j in range(1, M):
        qc.cx(sum_bit, senders[j * nq])
        qc.cx(carry_bit, senders[j * nq + 1])


def generate_qiskit_circuit(
    M,
    N,
    thetas,
    alphas=1 / np.sqrt(2),
    tau=None,
    delay_unit="dt",
    use_receiver_qec_513=False,
    use_structured_prep=False,
    linear_feedforward=True,
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
    use_receiver_qec_513 : bool, optional
        If True, encode each receiver qubit into a [[5,1,3]] block.
    use_structured_prep : bool, optional
        If True, replace the generic ``qc.initialize`` resource-state loading
        with :func:`structured_state_prep` (only implemented for ``N in {1,2}``;
        raises ``NotImplementedError`` otherwise). Default False for backward
        compatibility; use ``use_receiver_qec_513=True`` together with this is
        not yet supported (structured prep only builds the *unencoded* resource
        state so far — QEC encoding, if requested, is still applied afterwards
        via the existing encode-then-decode path, which is unaffected by this
        flag).
    linear_feedforward : bool, optional
        If True (default), implement the byproduct correction with
        ``M * nq`` single-bit-conditioned phase rotations instead of the
        ``(N+1)**M``-branch exponential feedforward. Mathematically identical
        for every *valid* sender outcome (phase corrections add linearly bit by
        bit); for an *invalid* outcome (register value > N, only possible when
        N+1 is not a power of two) it applies the same linear phase formula
        rather than skipping correction — see :func:`generate_qiskit_circuit`
        module docstring / ACTION_PLAN.md item 25 for this documented behavior
        change. Set False to reproduce the old exact (no-correction-on-invalid)
        behavior for direct comparison.

    Returns
    -------
    QuantumCircuit
        Dynamic circuit implementing protocol control flow.
    """
    if len(thetas) != M:
        raise ValueError(f"Expected {M} theta values, got {len(thetas)}.")

    nq = sender_encoding_qubits(N)
    n_sender_qubits = M * nq
    n_receiver_physical = 5 * N if use_receiver_qec_513 else N

    senders = QuantumRegister(n_sender_qubits, "a")
    receivers = QuantumRegister(n_receiver_physical, "r")
    c_senders = ClassicalRegister(n_sender_qubits, "m")
    qc = QuantumCircuit(senders, receivers, c_senders, name="MN_broadcast")

    if use_structured_prep:
        if use_receiver_qec_513:
            raise NotImplementedError(
                "use_structured_prep=True with use_receiver_qec_513=True is not "
                "yet supported; structured prep currently only covers the "
                "unencoded resource state."
            )
        structured_state_prep(qc, list(senders), list(receivers), M, N, nq, alphas)
    else:
        init_state = (
            build_initial_statevector_qec_513(M=M, N=N, alpha=alphas)
            if use_receiver_qec_513
            else build_initial_statevector(M=M, N=N, alpha=alphas)
        )
        qc.initialize(init_state, list(senders) + list(receivers))  # type: ignore

    tau_param = Parameter("tau") if tau is None else tau
    for qb in receivers:
        qc.delay(tau_param, qb, unit=delay_unit)

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

    Fdg = fourier_measurement_rotation(N=N, nq=nq)
    for j in range(M):
        qslice = [senders[j * nq + b] for b in range(nq)]
        cslice = [c_senders[j * nq + b] for b in range(nq)]
        qc.append(Fdg, qslice)
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
