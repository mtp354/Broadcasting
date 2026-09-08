"""Broadcasting protocol — M-sender, N-receiver quantum broadcasting with optional QEC."""

from .helpers import sender_encoding_qubits, packed_sender_value
from .qec_513 import (
    five_qubit_logical_basis,
    five_qubit_decode_gate,
    five_qubit_syndrome_corrections,
    decode_qec_513,
    qec_513_delay_benchmark_circuit,
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
from .protocol import ProtocolConfig, BroadcastResult
from .backend import ExactBackend, SamplingBackend, HPCBackend, HardwareBackend
from .results import save_run, load_run, list_runs, write_run_json

__all__ = [
    # helpers / primitives
    "sender_encoding_qubits",
    "packed_sender_value",
    # QEC [[5,1,3]]
    "five_qubit_logical_basis",
    "five_qubit_decode_gate",
    "five_qubit_syndrome_corrections",
    "decode_qec_513",
    "qec_513_delay_benchmark_circuit",
    # state preparation
    "build_initial_statevector",
    "build_initial_statevector_qec_513",
    # circuit
    "sender_phase_gate",
    "fourier_measurement_rotation",
    "generate_qiskit_circuit",
    # fidelity
    "add_fidelity",
    # protocol data model
    "ProtocolConfig",
    "BroadcastResult",
    # backends
    "ExactBackend",
    "SamplingBackend",
    "HPCBackend",
    "HardwareBackend",
    # results I/O
    "save_run",
    "write_run_json",
    "load_run",
    "list_runs",
]
