"""Backend ABC and concrete implementations for the broadcasting protocol.

Three execution backends:

* **ExactBackend** — full density-matrix simulation (local).
* **SamplingBackend** — Monte Carlo Pauli-trajectory simulation (local).
* **HardwareBackend** — transpile and submit to IBM Quantum hardware.
"""

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
        optimization_level: int = 3,
    ):
        self.service = service
        self.backend_name = backend_name
        self.shots = shots
        self.optimization_level = optimization_level

    def _backend(self) -> Any:
        if self.backend_name:
            return self.service.backend(self.backend_name)
        return self.service.least_busy(simulator=False, operational=True)

    @staticmethod
    def _fidelities_from_counts(counts: dict[str, int], N: int) -> list[float]:
        total = sum(counts.values())
        if total == 0:
            raise ValueError("Cannot compute fidelities from empty counts.")
        return [
            sum(v for bs, v in counts.items() if bs[N - 1 - i] == "0") / total
            for i in range(N)
        ]

    def run(self, config: ProtocolConfig) -> BroadcastResult:
        # Import here to avoid hard dependency when not using hardware
        from qiskit.transpiler import generate_preset_pass_manager
        from qiskit_ibm_runtime import SamplerV2 as Sampler

        from .circuit import generate_qiskit_circuit
        from .fidelity import add_fidelity

        backend = self._backend()

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
        pm = generate_preset_pass_manager(
            backend=backend,
            optimization_level=self.optimization_level,
        )
        isa_circuit = pm.run([qc])[0]

        # Submit
        sampler = Sampler(mode=backend)
        job = sampler.run([(isa_circuit,)], shots=self.shots)
        result = job.result()

        # Extract fidelities from measurement counts
        pub_result = result[0]
        fid_data = getattr(pub_result.data, reg_name)
        counts = fid_data.get_counts()
        fidelities = self._fidelities_from_counts(counts, config.N)

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
                "optimization_level": self.optimization_level,
                "tau": config.tau,
                "timestamp": datetime.now().isoformat(),
            },
        )

    def run_tau_sweep(
        self,
        config: ProtocolConfig,
        tau_values: list[int] | np.ndarray,
        *,
        theta_samples: list[list[float]] | np.ndarray | None = None,
    ) -> BroadcastResult:
        """Run a hardware tau sweep for one or more theta samples."""
        from qiskit.transpiler import generate_preset_pass_manager
        from qiskit_ibm_runtime import SamplerV2 as Sampler

        from .circuit import generate_qiskit_circuit
        from .fidelity import add_fidelity

        tau_values = [int(t) for t in tau_values]
        if not tau_values:
            raise ValueError("tau_values must contain at least one value.")

        if theta_samples is None:
            theta_samples = [list(config.thetas)]
        else:
            theta_samples = np.asarray(theta_samples, dtype=float).tolist()

        for sample in theta_samples:
            if len(sample) != config.M:
                raise ValueError(
                    f"Expected theta sample length {config.M}, got {len(sample)}."
                )

        backend = self._backend()
        circuits = []
        run_index: list[tuple[int, int]] = []
        reg_name = "fid"

        for ti, thetas in enumerate(theta_samples):
            qc = generate_qiskit_circuit(
                config.M,
                config.N,
                thetas,
                alphas=config.alpha,
                tau=None,
                use_receiver_qec_513=config.use_qec,
            )
            qc, reg_name, _ = add_fidelity(qc, N=config.N, thetas=thetas)
            tau_param = next(p for p in qc.parameters if p.name == "tau")

            for tau in tau_values:
                circuits.append(qc.assign_parameters({tau_param: tau}))
                run_index.append((ti, tau))

        pm = generate_preset_pass_manager(
            backend=backend,
            optimization_level=self.optimization_level,
        )
        isa_circuits = pm.run(circuits)
        job = Sampler(mode=backend).run(
            [(circuit,) for circuit in isa_circuits],
            shots=self.shots,
        )
        results = job.result()

        n_theta = len(theta_samples)
        n_tau = len(tau_values)
        tau_index = {tau: i for i, tau in enumerate(tau_values)}
        fid_grid: list[list[list[float] | None]] = [
            [None] * n_tau for _ in range(n_theta)
        ]
        counts_grid: list[list[dict[str, int] | None]] = [
            [None] * n_tau for _ in range(n_theta)
        ]

        for (ti, tau), pub_result in zip(run_index, results):
            counts = getattr(pub_result.data, reg_name).get_counts()
            j = tau_index[tau]
            fid_grid[ti][j] = self._fidelities_from_counts(counts, config.N)
            counts_grid[ti][j] = dict(counts)

        fidelities = np.mean(np.asarray(fid_grid, dtype=float), axis=0).tolist()

        return BroadcastResult(
            fidelities=fidelities,
            target_state=None,
            reduced_states=None,
            metadata={
                "mode": f"hardware ({backend.name})",
                "M": config.M,
                "N": config.N,
                "use_qec": config.use_qec,
                "thetas": list(config.thetas),
                "theta_samples": theta_samples,
                "p_list": config.p_list,
                "alpha": config.alpha,
                "shots": self.shots,
                "backend": backend.name,
                "job_id": job.job_id(),
                "optimization_level": self.optimization_level,
                "sweep_axis": "tau",
                "sweep_values": tau_values,
                "per_theta_fidelities": fid_grid if n_theta > 1 else None,
                "counts": counts_grid,
                "timestamp": datetime.now().isoformat(),
            },
        )
