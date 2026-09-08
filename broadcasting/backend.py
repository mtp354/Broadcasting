"""Backend ABC and concrete implementations for the broadcasting protocol.

Four execution backends, all sharing the same `Backend.run(config)` interface:

* **ExactBackend** — full density-matrix simulation (local).
* **SamplingBackend** — Monte Carlo Pauli-trajectory simulation (local).
* **HPCBackend** — builds (and optionally submits) a SLURM array job for `ExactBackend`/
  `SamplingBackend`-equivalent sweeps on a cluster.
* **HardwareBackend** — transpile and submit to IBM Quantum hardware.
"""

from abc import ABC, abstractmethod
from datetime import datetime
import subprocess
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


class HPCBackend(Backend):
    """Build (and optionally submit) a SLURM job running this config on the cluster.

    Translates a `ProtocolConfig` into environment variables consumed by
    `hpc/slurm_broadcast.sh` (which in turn calls `hpc.run_experiment`), so the
    same config object used for `ExactBackend`/`SamplingBackend` can be handed
    to the cluster without hand-writing an `sbatch` command.

    This does not run the simulation itself and does not return fidelities --
    `run()` only prepares (and, if `submit=True`, launches) the job. Fetch
    results afterwards the usual way (`rsync`/`scripts/fetch_results.sh` +
    `broadcasting.results.load_run`, or `scripts/merge_hpc_runs.py` first if
    `array=True` produced one file per sweep point).

    Parameters
    ----------
    mode : "exact" or "sampling"
        Matches `ExactBackend`/`SamplingBackend` -- passed through explicitly
        rather than inferred from `config.n_samples` (inferring from a
        default-truthy field was the exact bug fixed in `results.py`).
    script_path : str
        Path to the SLURM batch script.
    array : bool
        If True, submit one array task per sweep point (`--array=0-(steps-1)`).
        If False, a single task sweeps the whole `p_list` itself.
    concurrency : int | None
        Max concurrently-running array tasks (`--array=0-N%concurrency`).
    submit : bool
        If True, actually call `sbatch` (requires running where `sbatch` is on
        PATH, e.g. the HPC login node). If False (default), only build and
        return the command -- nothing is submitted.
    """

    def __init__(
        self,
        mode: str = "exact",
        script_path: str = "hpc/slurm_broadcast.sh",
        *,
        array: bool = False,
        concurrency: int | None = None,
        submit: bool = False,
    ):
        if mode not in ("exact", "sampling"):
            raise ValueError(f"mode must be 'exact' or 'sampling', got {mode!r}.")
        self.mode = mode
        self.script_path = script_path
        self.array = array
        self.concurrency = concurrency
        self.submit = submit

    def _env(self, config: ProtocolConfig) -> dict[str, str]:
        p_list = config.p_list or [0.0, 1.0]
        env = {
            "MODE": self.mode,
            "M": str(config.M),
            "N": str(config.N),
            "P_MIN": str(min(p_list)),
            "P_MAX": str(max(p_list)),
            "P_STEPS": str(len(p_list)),
            "N_SAMPLES": str(config.n_samples or 1000),
        }
        if config.use_qec:
            env["USE_QEC"] = "1"
        if config.alpha is not None:
            env["ALPHA"] = str(config.alpha)
        if config.thetas:
            env["THETAS"] = " ".join(str(t) for t in config.thetas)
        if config.outcomes_list:
            env["OUTCOMES"] = " ".join(str(o) for o in config.outcomes_list)
        if config.seed is not None:
            env["SEED"] = str(config.seed)
        return env

    def build_command(self, config: ProtocolConfig) -> list[str]:
        """Return the `sbatch` command for *config* without submitting it."""
        env = self._env(config)
        cmd = ["sbatch"]
        if self.array:
            array_range = f"0-{int(env['P_STEPS']) - 1}"
            if self.concurrency:
                array_range += f"%{self.concurrency}"
            cmd.append(f"--array={array_range}")
        cmd.append(f"--export=ALL,{','.join(f'{k}={v}' for k, v in env.items())}")
        cmd.append(self.script_path)
        return cmd

    def run(self, config: ProtocolConfig) -> BroadcastResult:
        cmd = self.build_command(config)

        job_id = None
        if self.submit:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            job_id = next((tok for tok in proc.stdout.split() if tok.isdigit()), None)

        return BroadcastResult(
            fidelities=[],
            metadata={
                "mode": f"hpc ({self.mode})",
                "command": " ".join(cmd),
                "submitted": self.submit,
                "job_id": job_id,
                "M": config.M,
                "N": config.N,
                "use_qec": config.use_qec,
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

    def _sampler(self, backend: Any) -> Any:
        from qiskit_ibm_runtime import SamplerV2 as Sampler

        return Sampler(mode=backend)

    @staticmethod
    def _fidelities_from_counts(counts: dict[str, int], N: int) -> list[float]:
        total = sum(counts.values())
        if total == 0:
            raise ValueError("Cannot compute fidelities from empty counts.")
        return [
            sum(v for bs, v in counts.items() if bs[N - 1 - i] == "0") / total
            for i in range(N)
        ]

    @staticmethod
    def _compute_invalid_sender_rate(counts: dict[str, int], M: int, N: int) -> float:
        """Compute the fraction of shots with out-of-range sender measurement values.

        Each sender qudit is represented by ``nq = ceil(log2(N + 1))`` bits.
        Values in ``{0, ..., N}`` are physically valid qudit outcomes; values
        ``> N`` are unphysical outcomes caused by measurement or circuit error.
        """
        from math import ceil, log2

        nq = int(ceil(log2(N + 1)))
        total_shots = sum(counts.values())
        if total_shots == 0:
            return 0.0

        L = M * nq
        invalid_shots = 0
        for bs, count in counts.items():
            clean_bs = bs.replace(" ", "")
            if len(clean_bs) != L:
                continue
            is_invalid = False
            for j in range(M):
                v_j = sum(
                    int(clean_bs[L - 1 - (j * nq + b)]) * (1 << b)
                    for b in range(nq)
                )
                if v_j > N:
                    is_invalid = True
                    break
            if is_invalid:
                invalid_shots += count

        return invalid_shots / total_shots

    def run(self, config: ProtocolConfig) -> BroadcastResult:
        # Import here to avoid hard dependency when not using hardware
        from qiskit.transpiler import generate_preset_pass_manager

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
            linear_feedforward=config.linear_feedforward,
        )
        qc, reg_name, phi = add_fidelity(
            qc, N=config.N, thetas=config.thetas, alpha=config.alpha
        )

        # Transpile
        pm = generate_preset_pass_manager(
            backend=backend,
            optimization_level=self.optimization_level,
        )
        isa_circuit = pm.run([qc])[0]

        # Submit
        sampler = self._sampler(backend)
        job = sampler.run([(isa_circuit,)], shots=self.shots)
        result = job.result()

        # Extract fidelities from measurement counts
        pub_result = result[0]
        fid_data = getattr(pub_result.data, reg_name)
        counts = fid_data.get_counts()
        fidelities = self._fidelities_from_counts(counts, config.N)

        sender_counts = None
        invalid_sender_rate = None
        if hasattr(pub_result.data, "c_senders"):
            sender_counts = dict(pub_result.data.c_senders.get_counts())
            invalid_sender_rate = self._compute_invalid_sender_rate(
                sender_counts, config.M, config.N
            )

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
                "sender_counts": sender_counts,
                "invalid_sender_rate": invalid_sender_rate,
                "optimization_level": self.optimization_level,
                "tau": config.tau,
                "dt": getattr(getattr(backend, "target", None), "dt", None),
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
        pm = generate_preset_pass_manager(
            backend=backend,
            optimization_level=self.optimization_level,
        )

        pubs = []
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
                linear_feedforward=config.linear_feedforward,
            )
            qc, reg_name, _ = add_fidelity(
                qc, N=config.N, thetas=thetas, alpha=config.alpha
            )

            # Transpile once per theta sample with tau left as a free Parameter,
            # then bind it per tau value below -- binding a transpiled circuit
            # is cheap, but transpiling one circuit per tau value (the previous
            # behavior) does full layout/routing/optimization len(tau_values)
            # times and can hang for a very long time before anything submits.
            print(
                f"Transpiling theta sample {ti + 1}/{len(theta_samples)} "
                f"(optimization_level={self.optimization_level})..."
            )
            isa_circuit = pm.run(qc)
            isa_tau_param = next(p for p in isa_circuit.parameters if p.name == "tau")

            for tau in tau_values:
                pubs.append((isa_circuit.assign_parameters({isa_tau_param: tau}),))
                run_index.append((ti, tau))

        print(f"Submitting job with {len(pubs)} PUB(s)...")
        job = self._sampler(backend).run(pubs, shots=self.shots)
        print(f"Job ID: {job.job_id()}")
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
        sender_counts_grid: list[list[dict[str, int] | None]] = [
            [None] * n_tau for _ in range(n_theta)
        ]
        invalid_rates_grid: list[list[float | None]] = [
            [None] * n_tau for _ in range(n_theta)
        ]

        has_sender_data = False
        for (ti, tau), pub_result in zip(run_index, results):
            counts = getattr(pub_result.data, reg_name).get_counts()
            j = tau_index[tau]
            fid_grid[ti][j] = self._fidelities_from_counts(counts, config.N)
            counts_grid[ti][j] = dict(counts)
            if hasattr(pub_result.data, "c_senders"):
                has_sender_data = True
                s_counts = dict(pub_result.data.c_senders.get_counts())
                sender_counts_grid[ti][j] = s_counts
                invalid_rates_grid[ti][j] = self._compute_invalid_sender_rate(
                    s_counts, config.M, config.N
                )

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
                "sender_counts": sender_counts_grid if has_sender_data else None,
                "invalid_sender_rate": invalid_rates_grid if has_sender_data else None,
                "dt": getattr(getattr(backend, "target", None), "dt", None),
                "timestamp": datetime.now().isoformat(),
            },
        )
