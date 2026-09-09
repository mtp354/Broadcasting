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
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit import Parameter
from qiskit.circuit.library import UnitaryGate


# Ordered generators shared by production circuit and numerical recovery code.
# Independent validation deliberately defines its own generators in tests.
QEC513_STABILIZERS = ("XZZXI", "IXZZX", "XIXZZ", "ZXIXZ")


def five_qubit_logical_basis() -> tuple[np.ndarray, np.ndarray]:
    """Return |0_L>, |1_L> for the [[5,1,3]] code (computational basis order)."""
    v0 = np.zeros(32, dtype=complex)
    plus_terms = ["00000", "10010", "01001", "10100", "01010", "00101"]
    minus_terms = [
        "11011", "00110", "11000", "11101", "00011",
        "11110", "01111", "10001", "01100", "10111",
    ]
    for bitstring in plus_terms:
        v0[int(bitstring, 2)] = 0.25
    for bitstring in minus_terms:
        v0[int(bitstring, 2)] = -0.25

    # Logical X flips all five physical bits: index i becomes 31 - i.
    v1 = v0[::-1].copy()
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
    basis = [v0 / np.linalg.norm(v0), v1 / np.linalg.norm(v1)]
    # Complete the two logical columns with Gram–Schmidt in computational order.
    for candidate in np.eye(32, dtype=complex).T:
        residual = candidate.copy()
        for column in basis:
            residual -= np.vdot(column, residual) * column
        norm = np.linalg.norm(residual)
        if norm > 1e-10:
            basis.append(residual / norm)
        if len(basis) == 32:
            break

    if len(basis) != 32:
        raise RuntimeError("Failed to construct a full decode basis for [[5,1,3]].")

    return UnitaryGate(np.column_stack(basis).conj().T, label="dec513")


def pauli_label_syndrome(label: str) -> str:
    """Return the four syndrome bits of a Pauli label, in stabilizer order.

    Two single-qubit Paulis anticommute exactly when both are nonidentity
    and different. A generator's syndrome bit is the parity of these positions.
    Label positions follow the tensor-factor order used by the stabilizers.
    """
    bits = []
    for stabilizer in QEC513_STABILIZERS:
        anticommutes = sum(
            error != "I" and generator != "I" and error != generator
            for error, generator in zip(label, stabilizer)
        )
        bits.append(str(anticommutes % 2))
    return "".join(bits)


def five_qubit_syndrome_corrections() -> dict[int, tuple[str, int] | None]:
    """Map 4-bit syndrome value to correction (Pauli, qubit index), or None for identity."""
    corrections: dict[int, tuple[str, int] | None] = {0: None}
    for qubit in range(5):
        for pauli in "XYZ":
            label = "I" * qubit + pauli + "I" * (4 - qubit)
            bits = pauli_label_syndrome(label)
            # Register bit 0 is the least significant bit of an if_test integer.
            syndrome = int(bits[::-1], 2)
            corrections[syndrome] = (pauli, qubit)
    return corrections


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
    stabilizers = QEC513_STABILIZERS

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


def qec_513_delay_benchmark_circuit(
    theta: float,
    phi: float,
    *,
    use_qec: bool = True,
    delay_unit: str = "dt",
):
    """Build a parametric delay-fidelity benchmark circuit.

    The circuit prepares ``Rz(phi) Ry(theta)|0>``, applies a symbolic
    delay named ``tau``, reverses the state preparation, and measures
    ``P(0)`` as the fidelity.  With ``use_qec=True`` the prepared qubit is
    first encoded into the [[5,1,3]] block and decoded after the delay.
    """
    tau = Parameter("tau")
    fid = ClassicalRegister(1, "fid_qec")

    if use_qec:
        data = QuantumRegister(5, "data")
        anc = QuantumRegister(4, "anc")
        qc = QuantumCircuit(data, anc, fid)
        decoded_source = data[0]
    else:
        data = QuantumRegister(1, "data")
        qc = QuantumCircuit(data, fid)
        decoded_source = data[0]

    qc.ry(theta, data[0])
    qc.rz(phi, data[0])

    if use_qec:
        qc.append(five_qubit_decode_gate().adjoint(), list(data))

    for q in data:
        qc.delay(tau, q, unit=delay_unit)

    if use_qec:
        decoded_source = qc.qubits[
            decode_qec_513(qc, [list(data)], ancilla_qubits=list(anc))[0]
        ]

    qc.rz(-phi, decoded_source)
    qc.ry(-theta, decoded_source)
    qc.measure(decoded_source, fid[0])
    return qc, tau, fid.name
