"""Fidelity measurement utilities for the broadcasting protocol."""

import numpy as np
from qiskit import ClassicalRegister


def add_fidelity(circuit, N, thetas, receiver_qubits=None):
    """
    Append basis-rotation gates and measurements so that, for each receiver qubit,
    P(measurement = 0) equals the fidelity to the target XY-plane state whose angle is

        phi = -2 * sum(thetas) mod 2*pi.

    This convention matches the reference notebook target
    |psi_target> = (exp(i*theta_total)|0> + exp(-i*theta_total)|1>) / sqrt(2)
    when alpha = 1/sqrt(2), beta = 1/sqrt(2), theta_total = sum(thetas).

    Parameters
    ----------
    circuit : QuantumCircuit
        Circuit to modify **in place**.
    N : int
        Number of receivers.
    thetas : sequence of float
        Sender angles (used to compute target phase).
    receiver_qubits : list[int] | None
        Qubit indices for receivers. If None, uses circuit metadata or
        defaults to the last N qubits.

    Returns
    -------
    circuit : QuantumCircuit
        The same circuit, modified in place.
    reg_name : str
        Name of the classical register holding fidelity measurements.
    phi : float
        Target-state angle in [0, 2*pi).
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

    existing_names = {creg.name for creg in circuit.cregs}
    base_name = "fid"
    reg_name = base_name
    k = 0
    while reg_name in existing_names:
        k += 1
        reg_name = f"{base_name}_{k}"

    fid_reg = ClassicalRegister(N, reg_name)
    circuit.add_register(fid_reg)

    for i, qb in enumerate(receiver_qubits):
        circuit.rz(-phi, qb)
        circuit.h(qb)
        circuit.measure(qb, fid_reg[i])

    return circuit, reg_name, phi
