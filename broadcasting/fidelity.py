"""Fidelity measurement utilities for the broadcasting protocol."""

import numpy as np
from qiskit import ClassicalRegister


def add_fidelity(circuit, N, thetas, alpha=1 / np.sqrt(2), receiver_qubits=None):
    """
    Append basis-rotation gates and measurements so that, for each receiver qubit,
    P(measurement = 0) equals the fidelity to the target state

        |psi_target> = alpha*exp(i*Phi)|0> + beta*exp(-i*Phi)|1>,
        Phi = sum(thetas), beta = sqrt(1 - alpha**2).

    The inverse rotation is built directly from the Bloch angle of the target
    state, ``Rz(2*Phi)`` then ``Ry(-2*arccos(alpha))``, which reduces to the
    circuit's previous hardcoded equatorial rotation (``Rz(-phi)`` then ``H``)
    up to an irrelevant global phase when ``alpha = 1/sqrt(2)``. For other
    values of `alpha` the old hardcoded rotation silently measured proximity to
    the equatorial state |+> instead of the true target and is no longer used.

    Parameters
    ----------
    circuit : QuantumCircuit
        Circuit to modify **in place**.
    N : int
        Number of receivers.
    thetas : sequence of float
        Sender angles (used to compute target phase).
    alpha : float
        Real amplitude parameter of the target state, ``-1 <= alpha <= 1``
        (default ``1/sqrt(2)``, the equatorial case used throughout the
        manuscript). Must be real; complex input is rejected.
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
        Target-state total sender angle `Phi = sum(thetas)`, in [0, 2*pi).
    """
    if N < 1:
        raise ValueError("N must be at least 1.")
    if N > circuit.num_qubits:
        raise ValueError(f"N={N} exceeds circuit.num_qubits={circuit.num_qubits}.")

    if np.iscomplexobj(alpha):
        raise ValueError("alpha must be real and in [-1, 1].")
    alpha = float(alpha)
    if not (-1.0 <= alpha <= 1.0):
        raise ValueError(f"alpha must be real and in [-1, 1], got {alpha}.")

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

    phi = float(np.mod(np.sum(thetas), 2 * np.pi))
    theta_bloch = 2.0 * np.arccos(np.clip(alpha, -1.0, 1.0))

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
        circuit.rz(2.0 * phi, qb)
        circuit.ry(-theta_bloch, qb)
        circuit.measure(qb, fid_reg[i])

    return circuit, reg_name, phi
