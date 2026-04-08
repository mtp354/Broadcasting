"""
[[5,1,3]] quantum error correction code.

Stabilizer generators: XZZXI, IXZZX, XIXZZ, ZXIXZ

Endianness convention
---------------------
All operations in this module follow Qiskit's little-endian convention:
qubit 0 is the least-significant bit of the state-vector index.

Palindrome symmetry
-------------------
The logical basis vectors |0_L> and |1_L> have bit-reversal palindrome
symmetry: v[i] == v[reverse_bits(i)] for all i.  This means that
reshape(order='C') and reshape(order='F') produce *identical* tensors
for these vectors.  Any test that only checks the logical basis will
pass regardless of reshape order --- end-to-end tests with N >= 2
(where the bare state breaks this symmetry) are required to catch
endianness bugs.
"""

import numpy as np
from qiskit import ClassicalRegister, QuantumRegister
from qiskit.circuit.library import UnitaryGate


def five_qubit_logical_basis() -> tuple[np.ndarray, np.ndarray]:
    """Return |0_L>, |1_L> for the [[5,1,3]] code (computational basis order)."""
    v0 = np.zeros(32, dtype=complex)
    plus_terms = ["00000", "10010", "01001", "10100", "01010", "00101"]
    minus_terms = ["11011","00110","11000","11101","00011","11110","01111","10001","01100","10111"]

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


def five_qubit_decode_gate() -> UnitaryGate:
    """
    Unitary ``U`` that decodes the [[5,1,3]] logical subspace to qubit 0.

    The mapping is fixed as
        U|0_L> = |00000>
        U|1_L> = |00001>

    so the decoded logical qubit is always carried by the first qubit in the
    Qiskit qubit list for each 5-qubit block (little-endian convention).
    """
    v0, v1 = five_qubit_logical_basis()
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
    U = W.conj().T
    return UnitaryGate(U, label="dec513")


def five_qubit_syndrome_corrections() -> dict[int, tuple[str, int] | None]:
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
        Circuit to modify **in place**.
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

    corrections = five_qubit_syndrome_corrections()
    decode_gate = five_qubit_decode_gate()
    stabilizers = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]

    output_qubits: list[int] = []

    for ell, block in enumerate(encoded_blocks):
        syn = ClassicalRegister(4, f"s{ell}")
        qc.add_register(syn)

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

        qc.append(decode_gate, block)

        output_qubits.append(qc.find_bit(block[0]).index)

    return output_qubits
