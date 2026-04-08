"""
Backward-compatibility facade.

This module re-exports everything from the ``broadcasting`` package under the
original underscore-prefixed names so that existing notebooks using
``import dynamic_broadcast as db`` continue to work unchanged.
"""

from broadcasting import (
    sender_encoding_qubits as _sender_encoding_qubits,
    packed_sender_value as _packed_sender_value,
    five_qubit_logical_basis as _five_qubit_logical_basis,
    five_qubit_decode_gate as _five_qubit_decode_gate,
    five_qubit_syndrome_corrections as _five_qubit_syndrome_corrections,
    decode_qec_513,
    build_initial_statevector as _build_initial_statevector,
    build_initial_statevector_qec_513 as _build_initial_statevector_qec_513,
    sender_phase_gate as _sender_phase_gate,
    fourier_measurement_rotation as _fourier_measurement_rotation,
    generate_qiskit_circuit,
    add_fidelity,
)
