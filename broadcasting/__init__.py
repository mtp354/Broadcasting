"""Broadcasting protocol — M-sender, N-receiver quantum broadcasting with optional QEC."""

from .helpers import sender_encoding_qubits, packed_sender_value
from .qec_513 import (
    five_qubit_logical_basis,
    five_qubit_decode_gate,
    five_qubit_syndrome_corrections,
    decode_qec_513,
)
from .state_preparation import (
    build_initial_statevector,
    build_initial_statevector_qec_513,
)
from .circuit import (
    sender_phase_gate,
    fourier_measurement_rotation,
    generate_qiskit_circuit,
)
from .fidelity import add_fidelity

__all__ = [
    "sender_encoding_qubits",
    "packed_sender_value",
    "five_qubit_logical_basis",
    "five_qubit_decode_gate",
    "five_qubit_syndrome_corrections",
    "decode_qec_513",
    "build_initial_statevector",
    "build_initial_statevector_qec_513",
    "sender_phase_gate",
    "fourier_measurement_rotation",
    "generate_qiskit_circuit",
    "add_fidelity",
]
