"""Backend ABC and concrete implementations for the broadcasting protocol.

Three execution backends:

* **ExactBackend** — full density-matrix simulation (local).
* **SamplingBackend** — Monte Carlo Pauli-trajectory simulation (local).
* **HardwareBackend** — transpile and submit to IBM Quantum hardware.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import numpy as np
from qiskit.quantum_info import Statevector

from .protocol import BroadcastResult, ProtocolConfig
from .simulation import (
    run_broadcast_no_qec,
    run_broadcast_qec,
)


class Backend(ABC):
    """Abstract base for broadcasting protocol execution."""

    @abstractmethod
    def run(self, config: ProtocolConfig) -> BroadcastResult:
        """Execute the protocol and return results.

        Parameters
        ----------
        config : ProtocolConfig
            Protocol parameters.

        Returns
        -------
        BroadcastResult
        """


class ExactBackend(Backend):
    """Full density-matrix simulation.

    Uses exact channel evolution on the complete Hilbert space.  Practical
    only for small systems.
    """

    def run(self, config: ProtocolConfig) -> BroadcastResult:
        all_fidelities = []
        target = None
        last_reduced = None

        runner = run_broadcast_qec if config.use_qec else run_broadcast_no_qec
        extra = {"mode": "exact"} if config.use_qec else {}

        for p in config.p_list:
            fids, target, last_reduced = runner(
                M=config.M,
                N=config.N,
                alpha=config.alpha,
                theta_list=config.thetas,
                p_list=[p] * config.N,
                outcomes_list=config.outcomes_list,
                seed=config.seed,
                **extra,
            )
            all_fidelities.append(fids)

        return BroadcastResult(
            fidelities=all_fidelities,
            target_state=np.asarray(target) if target is not None else None,
            reduced_states=last_reduced,
            metadata={
                "mode": "exact",
                "M": config.M,
                "N": config.N,
                "use_qec": config.use_qec,
                "thetas": config.thetas,
                "p_list": config.p_list,
                "alpha": config.alpha,
                "timestamp": datetime.now().isoformat(),
            },
        )


class SamplingBackend(Backend):
    """Monte Carlo Pauli-trajectory simulation.

    Only applicable when QEC is enabled — each trajectory samples a
    random Pauli error on the 5-qubit blocks and the density matrix is
    estimated from the ensemble.

    Parameters
    ----------
    n_samples : int
        Number of trajectories.
    seed : int or None
        RNG seed for reproducibility.
    """

    def __init__(self, n_samples: int = 200, seed: int | None = None):
        self.n_samples = n_samples
        self.seed = seed

    def run(self, config: ProtocolConfig) -> BroadcastResult:
        if not config.use_qec:
            raise ValueError(
                "SamplingBackend requires use_qec=True.  For non-QEC "
                "simulations use ExactBackend (density matrices are small "
                "enough without the 5-qubit encoding)."
            )

        seed = self.seed if config.seed is None else config.seed
        all_fidelities = []
        target = None
        last_reduced = None

        for p in config.p_list:
            fids, target, last_reduced = run_broadcast_qec(
                M=config.M,
                N=config.N,
                alpha=config.alpha,
                theta_list=config.thetas,
                p_list=[p] * config.N,
                outcomes_list=config.outcomes_list,
                mode="sampling",
                n_samples=self.n_samples,
                seed=seed,
            )
            all_fidelities.append(fids)

        return BroadcastResult(
            fidelities=all_fidelities,
            target_state=np.asarray(target) if target is not None else None,
            reduced_states=last_reduced,
            metadata={
                "mode": f"sampled ({self.n_samples} trajectories)",
                "M": config.M,
                "N": config.N,
                "use_qec": config.use_qec,
                "thetas": config.thetas,
                "p_list": config.p_list,
                "alpha": config.alpha,
                "n_samples": self.n_samples,
                "timestamp": datetime.now().isoformat(),
            },
        )


class HardwareBackend(Backend):
    """IBM Quantum hardware execution.

    Parameters
    ----------
    service : QiskitRuntimeService
        Authenticated runtime service.
    backend_name : str or None
        Specific backend name.  If None, uses the least-busy backend.
    shots : int
        Number of measurement shots per circuit.
    """

    def __init__(
        self,
        service: Any,
        backend_name: str | None = None,
        shots: int = 8192,
    ):
        self.service = service
        self.backend_name = backend_name
        self.shots = shots

    def run(self, config: ProtocolConfig) -> BroadcastResult:
        # Import here to avoid hard dependency when not using hardware
        from qiskit.transpiler import generate_preset_pass_manager
        from qiskit_ibm_runtime import SamplerV2 as Sampler

        from .circuit import generate_qiskit_circuit
        from .fidelity import add_fidelity

        # Select backend
        if self.backend_name:
            backend = self.service.backend(self.backend_name)
        else:
            backend = self.service.least_busy(simulator=False, operational=True)

        # Build circuit
        qc = generate_qiskit_circuit(
            config.M,
            config.N,
            config.thetas,
            alphas=config.alpha,
            tau=config.tau,
            use_receiver_qec_513=config.use_qec,
        )
        qc, reg_name, phi = add_fidelity(qc, N=config.N, thetas=config.thetas)

        # Transpile
        pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
        isa_circuit = pm.run([qc])[0]

        # Submit
        sampler = Sampler(mode=backend)
        job = sampler.run([(isa_circuit,)], shots=self.shots)
        result = job.result()

        # Extract fidelities from measurement counts
        pub_result = result[0]
        fid_data = getattr(pub_result.data, reg_name)
        counts = fid_data.get_counts()
        total = sum(counts.values())

        fidelities = []
        for i in range(config.N):
            p0 = sum(
                v for bs, v in counts.items()
                if bs[config.N - 1 - i] == "0"
            ) / total
            fidelities.append(p0)

        return BroadcastResult(
            fidelities=fidelities,
            target_state=None,
            reduced_states=None,
            metadata={
                "mode": f"hardware ({backend.name})",
                "M": config.M,
                "N": config.N,
                "use_qec": config.use_qec,
                "thetas": config.thetas,
                "p_list": config.p_list,
                "alpha": config.alpha,
                "shots": self.shots,
                "backend": backend.name,
                "job_id": job.job_id(),
                "counts": counts,
                "tau": config.tau,
                "timestamp": datetime.now().isoformat(),
            },
        )
