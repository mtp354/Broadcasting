import itertools
from math import ceil, log2
import numpy as np
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit import Parameter
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


def _five_qubit_logical_basis() -> tuple[np.ndarray, np.ndarray]:
    """Return |0_L>, |1_L> for the [[5,1,3]] code (computational basis order)."""
    v0 = np.zeros(32, dtype=complex)
    plus_terms = ["00000", "10010", "01001", "10100", "01010", "00101"]
    minus_terms = [
        "11011",
        "00110",
        "11000",
        "11101",
        "00011",
        "11110",
        "01111",
        "10001",
        "01100",
        "10111",
    ]

    def bits_to_index(bitstr: str) -> int:
        idx = 0
        for ch in bitstr:
            idx = (idx << 1) | int(ch)
        return idx

    for s in plus_terms:
        v0[bits_to_index(s)] += 0.25
    for s in minus_terms:
        v0[bits_to_index(s)] -= 0.25

    v1 = np.zeros(32, dtype=complex)
    for idx, amp in enumerate(v0):
        if amp != 0:
            v1[idx ^ 0b11111] = amp
    return v0, v1


def _build_initial_statevector_qec_513(M: int, N: int, alpha: complex) -> np.ndarray:
    """
    Build |Psi^(M,N)> with each receiver qubit encoded into a [[5,1,3]] block.

    Important ordering convention (matches generate_qiskit_circuit):
    - Sender *qubits* stay unchanged and remain first.
    - Receiver logical qubits are encoded one-by-one into 5 physical qubits.
    """
    logical = _build_initial_statevector(M=M, N=N, alpha=alpha)
    v0, v1 = _five_qubit_logical_basis()
    nq = _sender_encoding_qubits(N)
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


def _five_qubit_decode_gate() -> UnitaryGate:
    """
    Unitary ``U`` that decodes the [[5,1,3]] logical subspace to qubit 0.

    The mapping is fixed as
        U|0_L> = |00000>
        U|1_L> = |00001>

    so the decoded logical qubit is always carried by the first qubit in the
    Qiskit qubit list for each 5-qubit block (little-endian convention).
    """
    v0, v1 = _five_qubit_logical_basis()
    # Build an orthonormal basis with v0 and v1 explicitly as the first two
    # vectors, then complete with computational basis vectors.
    cols: list[np.ndarray] = [v0 / np.linalg.norm(v0), v1 / np.linalg.norm(v1)]
    eye = np.eye(32, dtype=complex)
    for cand in eye.T:
        w = cand.astype(complex)
        for c in cols:
            w = w - np.vdot(c, w) * c
        nrm = np.linalg.norm(w)
        if nrm > 1e-10:
            cols.append(w / nrm)
        if len(cols) == 32:
            break

    if len(cols) != 32:
        raise RuntimeError("Failed to construct a full decode basis for [[5,1,3]].")

    W = np.column_stack(cols)
    # W maps computational basis -> physical basis, so U = W^† performs decode.
    U = W.conj().T
    return UnitaryGate(U, label="dec513")


def _five_qubit_syndrome_corrections() -> dict[int, tuple[str, int] | None]:
    """Map 4-bit syndrome value to correction (Pauli, qubit index), or None for identity."""
    I2 = np.eye(2, dtype=complex)
    X = np.array([[0, 1], [1, 0]], dtype=complex)
    Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    Z = np.array([[1, 0], [0, -1]], dtype=complex)
    pauli_dict = {"I": I2, "X": X, "Y": Y, "Z": Z}
    g_labels = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]

    def kron_all(mats):
        out = mats[0]
        for m in mats[1:]:
            out = np.kron(out, m)
        return out

    G = [kron_all([pauli_dict[c] for c in lbl]) for lbl in g_labels]

    def syndrome_of(E):
        bits = []
        for g in G:
            comm = E @ g - g @ E
            anticomm = E @ g + g @ E
            if np.linalg.norm(comm) < 1e-8:
                bits.append("0")
            elif np.linalg.norm(anticomm) < 1e-8:
                bits.append("1")
            else:
                raise RuntimeError("Syndrome detection failed.")

        # Qiskit interprets a ClassicalRegister condition as little-endian:
        # register[0] is the least significant bit of the integer value.
        # Syndromes are generated in stabilizer order (s0,s1,s2,s3), so we
        # reverse before converting to the integer used in `if_test`.
        return int("".join(bits[::-1]), 2)

    corr: dict[int, tuple[str, int] | None] = {0: None}
    for q in range(5):
        for p in ("X", "Y", "Z"):
            mats = [I2] * 5
            mats[q] = pauli_dict[p]
            s = syndrome_of(kron_all(mats))
            corr[s] = (p, q)
    return corr


def decode_qec_513(qc, encoded_blocks, ancilla_qubits=None):
    """
    Decode [[5,1,3]]-encoded qubit blocks in place.

    Assumes that each group of 5 qubits in *encoded_blocks* already carries a
    logical qubit encoded in the [[5,1,3]] stabiliser code.  For every block
    this function appends:

    1. Syndrome extraction using the four stabiliser generators
       ``XZZXI, IXZZX, XIXZZ, ZXIXZ`` and 4 shared ancilla qubits.
    2. Classical feedforward: a conditional Pauli correction selected by the
       measured 4-bit syndrome value.
    3. The 5-qubit decode unitary that maps ``|0_L> -> |00000>`` and
       ``|1_L> -> |00001>``, so the decoded logical information ends up on the
       **first** qubit of each block (Qiskit little-endian convention).

    Parameters
    ----------
    qc : QuantumCircuit
        Circuit to modify **in place**.  Must already contain the qubits
        referenced by *encoded_blocks* (and *ancilla_qubits*, if supplied).
    encoded_blocks : list[list[Qubit | int]]
        Each element is a length-5 sequence identifying the physical qubits of
        one [[5,1,3]] block, in stabiliser order.
    ancilla_qubits : list[Qubit | int] | None
        Four ancilla qubits used (and reused) for syndrome measurement.  If
        ``None`` a fresh ``QuantumRegister(4, "syn")`` is added to *qc*.

    Returns
    -------
    list[int]
        Global qubit indices carrying the decoded logical qubits (one per
        block).  These are always the first qubit of each block.
    """
    if not encoded_blocks:
        return []

    for i, block in enumerate(encoded_blocks):
        if len(block) != 5:
            raise ValueError(
                f"encoded_blocks[{i}] has {len(block)} qubits; expected 5."
            )

    # Ancilla qubits -----------------------------------------------------------
    if ancilla_qubits is None:
        anc = QuantumRegister(4, "syn")
        qc.add_register(anc)
        ancilla_qubits = list(anc)
    else:
        ancilla_qubits = list(ancilla_qubits)
        if len(ancilla_qubits) != 4:
            raise ValueError(
                f"ancilla_qubits has {len(ancilla_qubits)} qubits; expected 4."
            )

    corrections = _five_qubit_syndrome_corrections()
    decode_gate = _five_qubit_decode_gate()
    stabilizers = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]

    output_qubits: list[int] = []

    for ell, block in enumerate(encoded_blocks):
        # Classical register for this block's syndrome bits.
        syn = ClassicalRegister(4, f"s{ell}")
        qc.add_register(syn)

        # --- Syndrome extraction ---
        for sid, stab in enumerate(stabilizers):
            qc.reset(ancilla_qubits[sid])
            for qb, p in zip(block, stab):
                if p == "X":
                    qc.h(qb)
                    qc.cx(qb, ancilla_qubits[sid])
                    qc.h(qb)
                elif p == "Y":
                    qc.sdg(qb)
                    qc.h(qb)
                    qc.cx(qb, ancilla_qubits[sid])
                    qc.h(qb)
                    qc.s(qb)
                elif p == "Z":
                    qc.cx(qb, ancilla_qubits[sid])
            qc.measure(ancilla_qubits[sid], syn[sid])

        # --- Classical feedforward corrections ---
        for syndrome_value, correction in corrections.items():
            if correction is None:
                continue
            pauli, qidx = correction
            with qc.if_test((syn, syndrome_value)):
                if pauli == "X":
                    qc.x(block[qidx])
                elif pauli == "Y":
                    qc.y(block[qidx])
                elif pauli == "Z":
                    qc.z(block[qidx])

        # --- Decode ---
        qc.append(decode_gate, block)

        output_qubits.append(qc.find_bit(block[0]).index)

    return output_qubits


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


def add_fidelity(circuit, N, thetas, receiver_qubits=None):
    """
    Append basis-rotation gates and measurements so that, for each receiver qubit,
    P(measurement = 0) equals the fidelity to the target XY-plane state whose angle is

        phi = -2 * sum(thetas) mod 2*pi.

    This convention matches the reference notebook target
    |psi_target> = (exp(i*theta_total)|0> + exp(-i*theta_total)|1>) / sqrt(2)
    when alpha = 1/sqrt(2), beta = 1/sqrt(2), theta_total = sum(thetas).

    Assumptions:
    - By default, receivers are assumed to be the last N qubits in the circuit.
    This matches `generate_qiskit_circuit` where receiver register comes after senders.
    - These qubits are in their final output state at the point this function is called.
    - They have not already been irreversibly measured/reset in a way that destroys the final state you want to test.

    Mutates:
    - `circuit` in place.

    Returns:
    circuit   : the same circuit object, after modification
    reg_name  : name of the new classical register holding the fidelity measurements
    phi       : target-state angle in [0, 2*pi)
    """
    if N < 1:
        raise ValueError("N must be at least 1.")
    if N > circuit.num_qubits:
        raise ValueError(f"N={N} exceeds circuit.num_qubits={circuit.num_qubits}.")

    if receiver_qubits is None:
        metadata = getattr(circuit, "metadata", None) or {}
        receiver_qubits = metadata.get(
            "receiver_output_qubits",
            list(range(circuit.num_qubits - N, circuit.num_qubits)),
        )
    else:
        receiver_qubits = list(receiver_qubits)

    if len(receiver_qubits) != N:
        raise ValueError(
            f"receiver_qubits length ({len(receiver_qubits)}) must match N ({N})."
        )
    if any(q < 0 or q >= circuit.num_qubits for q in receiver_qubits):
        raise ValueError("receiver_qubits contains an out-of-range qubit index.")

    phi = float(np.mod(-2.0 * np.sum(thetas), 2 * np.pi))

    # Create a unique classical register name.
    existing_names = {creg.name for creg in circuit.cregs}
    base_name = "fid"
    reg_name = base_name
    k = 0
    while reg_name in existing_names:
        k += 1
        reg_name = f"{base_name}_{k}"

    fid_reg = ClassicalRegister(N, reg_name)
    circuit.add_register(fid_reg)

    # Rotate each qubit so that the target state maps to |0>, then measure.
    for i, qb in enumerate(receiver_qubits):
        circuit.rz(-phi, qb)
        circuit.h(qb)
        circuit.measure(qb, fid_reg[i])

    return circuit, reg_name, phi


def generate_qiskit_circuit(
    M,
    N,
    thetas,
    alphas=1 / np.sqrt(2),
    tau=None,
    delay_unit="dt",
    use_receiver_qec_513=False,
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

    Returns
    -------
    QuantumCircuit
        Dynamic circuit implementing protocol control flow.
    """
    if len(thetas) != M:
        raise ValueError(f"Expected {M} theta values, got {len(thetas)}.")

    nq = _sender_encoding_qubits(N)
    n_sender_qubits = M * nq
    n_receiver_physical = 5 * N if use_receiver_qec_513 else N

    senders = QuantumRegister(n_sender_qubits, "a")
    receivers = QuantumRegister(n_receiver_physical, "r")
    c_senders = ClassicalRegister(n_sender_qubits, "m")
    qc = QuantumCircuit(senders, receivers, c_senders, name="MN_broadcast")

    init_state = (
        _build_initial_statevector_qec_513(M=M, N=N, alpha=alphas)
        if use_receiver_qec_513
        else _build_initial_statevector(M=M, N=N, alpha=alphas)
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
            for qb in active_receivers:
                qc.p(-phase, qb)

    return qc
