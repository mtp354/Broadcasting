"""Backend ABC and concrete implementations for the broadcasting protocol.

Four execution backends, all sharing the same `Backend.run(config)` interface:

* **ExactBackend** — full density-matrix simulation (local).
* **SamplingBackend** — Monte Carlo Pauli-trajectory simulation (local).
* **HPCBackend** — builds (and optionally submits) a SLURM array job for `ExactBackend`/
  `SamplingBackend`-equivalent sweeps on a cluster.
* **HardwareBackend** — transpile and submit to IBM Quantum hardware.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from dataclasses import asdict
import subprocess
import shlex
import time
import math
import json
from typing import Any

import numpy as np

from .protocol import BroadcastResult, ProtocolConfig
from .provenance import software_provenance, circuit_provenance, calibration_provenance
from .simulation import (
    run_broadcast_no_qec,
    run_broadcast_qec,
)


def _validate_config(config: ProtocolConfig, *, probabilities: bool = False) -> None:
    for name in ("M", "N"):
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    if np.iscomplexobj(config.alpha) or not np.isfinite(config.alpha) or not -1 <= config.alpha <= 1:
        raise ValueError("alpha must be real and in [-1, 1].")
    if len(config.thetas) != config.M or np.iscomplexobj(config.thetas) or not np.all(np.isfinite(config.thetas)):
        raise ValueError(f"Expected {config.M} finite real theta values.")
    if config.outcomes_list is not None:
        if len(config.outcomes_list) != config.M or any(
            isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 0 <= value <= config.N
            for value in config.outcomes_list
        ):
            raise ValueError(f"outcomes_list must contain {config.M} integers in [0, {config.N}].")
    if probabilities and (not len(config.p_list) or np.iscomplexobj(config.p_list) or any(
        not np.isfinite(value) or not 0 <= value <= 1 for value in config.p_list
    )):
        raise ValueError("p_list must contain finite probabilities in [0, 1].")


def _sampler_settings(sampler) -> dict:
    """Only execution controls are recorded; exclude account/environment objects."""
    from dataclasses import asdict, is_dataclass
    options = getattr(sampler, "options", None)
    def plain(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if is_dataclass(value):
            return plain(asdict(value))
        if isinstance(value, dict):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(item) for item in value]
        return str(value)
    return {name: plain(getattr(options, name)) for name in
            ("default_shots", "max_execution_time", "dynamical_decoupling", "execution", "twirling")
            if hasattr(options, name)}


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
        _validate_config(config, probabilities=True)
        software = software_provenance()
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
                "seed": config.seed,
                "M": config.M,
                "N": config.N,
                "use_qec": config.use_qec,
                "thetas": config.thetas,
                "p_list": config.p_list,
                "alpha": config.alpha,
                "linear_feedforward": config.linear_feedforward,
                "outcomes_list": config.outcomes_list,
                "software": software,
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
        _validate_config(config, probabilities=True)
        software = software_provenance()
        if not config.use_qec:
            raise ValueError(
                "SamplingBackend requires use_qec=True.  For non-QEC "
                "simulations use ExactBackend (density matrices are small "
                "enough without the 5-qubit encoding)."
            )

        seed = self.seed if config.seed is None else config.seed
        n_samples = self.n_samples if config.n_samples is None else config.n_samples
        if isinstance(n_samples, bool) or not isinstance(n_samples, (int, np.integer)) or n_samples < 1:
            raise ValueError("n_samples must be a positive integer.")
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
                n_samples=n_samples,
                seed=seed,
            )
            all_fidelities.append(fids)

        return BroadcastResult(
            fidelities=all_fidelities,
            target_state=np.asarray(target) if target is not None else None,
            reduced_states=last_reduced,
            metadata={
                "mode": f"sampled ({n_samples} trajectories)",
                "M": config.M,
                "N": config.N,
                "use_qec": config.use_qec,
                "thetas": config.thetas,
                "p_list": config.p_list,
                "alpha": config.alpha,
                "linear_feedforward": config.linear_feedforward,
                "outcomes_list": config.outcomes_list,
                "software": software,
                "n_samples": n_samples,
                "seed": seed,
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
    results afterwards with `hpc/fetch_results.sh` and
    `broadcasting.results.load_run`. Use `python -m broadcasting.merge_hpc_runs` first if
    `array=True` produced one file per sweep point.

    Parameters
    ----------
    mode : "exact" or "sampling"
        Select the numerical runner explicitly, independent of n_samples.
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
        _validate_config(config, probabilities=True)
        if self.mode == "sampling" and not config.use_qec:
            raise ValueError("HPC sampling requires use_qec=True.")
        p_list = list(config.p_list)
        if not p_list or any(not np.isfinite(p) or not 0 <= p <= 1 for p in p_list):
            raise ValueError("p_list must contain finite probabilities in [0, 1].")
        if len(set(p_list)) != len(p_list):
            raise ValueError("p_list must not contain duplicates.")
        env = {
            "MODE": self.mode,
            "M": str(config.M),
            "N": str(config.N),
            "P_LIST": " ".join(str(p) for p in p_list),
            "P_MIN": str(min(p_list)),
            "P_MAX": str(max(p_list)),
            "P_STEPS": str(len(p_list)),
            "N_SAMPLES": str(200 if config.n_samples is None else config.n_samples),
            "USE_QEC": "1" if config.use_qec else "0",
            "LINEAR_FEEDFORWARD": "1" if config.linear_feedforward else "0",
            "THETAS": " ".join(str(t) for t in config.thetas),
            "OUTCOMES": " ".join(str(o) for o in config.outcomes_list) if config.outcomes_list is not None else "random",
            "SEED": "" if config.seed is None else str(config.seed),
        }
        if config.alpha is not None:
            env["ALPHA"] = str(config.alpha)
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
                "command": shlex.join(cmd),
                "argv": cmd,
                "requested_sweep_values": list(config.p_list),
                "n_samples": 200 if config.n_samples is None else config.n_samples,
                "seed": config.seed,
                "linear_feedforward": config.linear_feedforward,
                "outcomes_list": config.outcomes_list,
                "software": software_provenance(),
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
        *,
        seed_transpiler: int | None = None,
        initial_layout: list[int] | None = None,
    ):
        self.seed_transpiler = seed_transpiler
        self.initial_layout = initial_layout
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

    @staticmethod
    def _validate_taus(tau_values) -> list[int]:
        values = list(tau_values)
        if not values:
            raise ValueError("tau_values must contain at least one value.")
        taus = []
        for tau in values:
            if isinstance(tau, (bool, complex)) or not isinstance(tau, (int, float, np.integer, np.floating)):
                raise ValueError("tau values must be finite nonnegative integer dt durations.")
            if not np.isfinite(tau) or tau < 0 or tau != int(tau):
                raise ValueError("tau values must be finite nonnegative integer dt durations.")
            taus.append(int(tau))
        if len(set(taus)) != len(taus):
            raise ValueError("tau_values must not contain duplicate delays.")
        return taus

    @staticmethod
    def _aligned_shots(data) -> dict:
        """Preserve register columns in original shot order, including syndromes."""
        items = data.items() if hasattr(data, "items") else vars(data).items()
        registers = {name: value.get_bitstrings() for name, value in items
                     if hasattr(value, "get_bitstrings")}
        if registers and len({len(values) for values in registers.values()}) != 1:
            raise ValueError("Classical registers have inconsistent shot counts.")
        return {"ordering": "register bitstrings are MSB first; equal indices identify the same shot",
                "registers": registers,
                "num_shots": len(next(iter(registers.values()))) if registers else None,
                "available": bool(registers)}

    @staticmethod
    def _validate_target(circuits, backend):
        target = getattr(backend, "target", None)
        if target is not None and hasattr(target, "instruction_supported"):
            from qiskit_ibm_runtime.utils.validations import validate_isa_circuits
            validate_isa_circuits(circuits, target)
        if any(circuit.parameters for circuit in circuits):
            raise ValueError("Cannot submit circuits containing unbound parameters.")

    def run(self, config: ProtocolConfig) -> BroadcastResult:
        """Run one delay point; the omitted delay is explicitly zero dt."""
        tau = 0 if config.tau is None else config.tau
        result = self.run_tau_sweep(config, [tau])
        result.fidelities = result.fidelities[0]
        meta = result.metadata
        meta["tau"] = meta.pop("sweep_values")[0]
        meta.pop("sweep_axis")
        for name in ("counts", "sender_counts", "invalid_sender_rate", "aligned_shots"):
            if meta.get(name) is not None:
                meta[name] = meta[name][0][0]
        return result

    def prepare_tau_sweep(
        self,
        config: ProtocolConfig,
        tau_values: list[int] | np.ndarray,
        *,
        theta_samples: list[list[float]] | np.ndarray | None = None,
        receiver_delay_factors: list[int] | None = None,
        backend=None,
    ) -> dict:
        """Compile and archive a delay sweep without constructing a sampler.

        Symbolic-delay compilation is reused once per theta where supported.
        Targets rejecting symbolic durations are compiled at each bound delay;
        the chosen path and replayable compiled templates are archived.
        """
        from qiskit.transpiler import generate_preset_pass_manager, TranspilerError
        from .circuit import generate_qiskit_circuit
        from .fidelity import add_fidelity

        started = time.perf_counter()
        _validate_config(config)
        if isinstance(self.shots, bool) or not isinstance(self.shots, int) or self.shots < 1:
            raise ValueError("shots must be a positive integer.")
        if self.optimization_level not in (0, 1, 2, 3):
            raise ValueError("optimization_level must be 0, 1, 2, or 3.")
        software = software_provenance()
        tau_values = self._validate_taus(tau_values)
        theta_samples = [config.thetas] if theta_samples is None else theta_samples
        if np.iscomplexobj(theta_samples):
            raise ValueError("theta samples must be real.")
        theta_samples = np.asarray(theta_samples, dtype=float)
        if theta_samples.ndim != 2 or theta_samples.shape[0] == 0 or theta_samples.shape[1] != config.M:
            raise ValueError(f"theta_samples must contain samples of length {config.M}.")
        if not np.all(np.isfinite(theta_samples)):
            raise ValueError("theta samples must be finite.")
        theta_samples = theta_samples.tolist()
        if np.iscomplexobj(config.alpha) or not np.isfinite(config.alpha) or not -1 <= config.alpha <= 1:
            raise ValueError("alpha must be real and in [-1, 1].")
        backend = self._backend() if backend is None else backend
        target = getattr(backend, "target", None)
        granularity = getattr(target, "granularity", 1) or 1
        alignment = getattr(target, "pulse_alignment", 1) or 1
        step = math.lcm(granularity, alignment)
        if any(tau % step for tau in tau_values):
            raise ValueError(f"tau values must be multiples of {step} dt for {backend.name}.")
        effective_layout = self.initial_layout
        pm = generate_preset_pass_manager(
            backend=backend, optimization_level=self.optimization_level,
            seed_transpiler=self.seed_transpiler, initial_layout=effective_layout,
        )
        pubs, templates, compiled_pubs, compile_modes = [], [], [], []
        reg_name = "fid"
        for ti, thetas in enumerate(theta_samples):
            qc = generate_qiskit_circuit(config.M, config.N, thetas, alphas=config.alpha,
                                        tau=None, use_receiver_qec_513=config.use_qec,
                                        linear_feedforward=config.linear_feedforward,
                                        receiver_delay_factors=receiver_delay_factors)
            qc, reg_name, _ = add_fidelity(qc, N=config.N, thetas=thetas, alpha=config.alpha)
            print(f"Transpiling theta sample {ti + 1}/{len(theta_samples)} "
                  f"(optimization_level={self.optimization_level})...")
            try:
                isa_circuit = pm.run(qc)
            except TranspilerError as exc:
                # Only a symbolic-duration failure justifies a bound fallback.
                message = str(exc).lower()
                if not any(word in message for word in ("duration", "parameter", "delay")):
                    raise
                compile_modes.append({"theta_index": ti, "mode": "bound per delay", "reason": str(exc)})
                tau_parameter = next(p for p in qc.parameters if p.name == "tau")
                for j, tau in enumerate(tau_values):
                    bound = pm.run(qc.assign_parameters({tau_parameter: tau}))
                    if effective_layout is None and bound.layout is not None:
                        effective_layout = bound.layout.initial_index_layout(filter_ancillas=True)
                        pm = generate_preset_pass_manager(
                            backend=backend, optimization_level=self.optimization_level,
                            seed_transpiler=self.seed_transpiler, initial_layout=effective_layout,
                        )
                    template_index = len(templates)
                    templates.append(circuit_provenance(bound, target))
                    pubs.append((bound,))
                    compiled_pubs.append({"theta_index": ti, "tau_index": j, "tau_dt": tau,
                                          "template_index": template_index, "bindings": {}})
            else:
                tau_parameter = next((p for p in isa_circuit.parameters if p.name == "tau"), None)
                if tau_parameter is None:
                    raise ValueError("Transpilation removed the sweep's tau parameter.")
                template_index = len(templates)
                templates.append(circuit_provenance(isa_circuit, target))
                compile_modes.append({"theta_index": ti, "mode": "symbolic once per theta"})
                for j, tau in enumerate(tau_values):
                    bound = isa_circuit.assign_parameters({tau_parameter: tau})
                    pubs.append((bound,))
                    compiled_pubs.append({"theta_index": ti, "tau_index": j, "tau_dt": tau,
                                          "template_index": template_index, "bindings": {"tau": tau}})
            # Freeze the first chosen input mapping for later theta samples.
            if effective_layout is None and pubs[-1][0].layout is not None:
                effective_layout = pubs[-1][0].layout.initial_index_layout(filter_ancillas=True)
                pm = generate_preset_pass_manager(
                    backend=backend, optimization_level=self.optimization_level,
                    seed_transpiler=self.seed_transpiler, initial_layout=effective_layout,
                )
        self._validate_target([pub[0] for pub in pubs], backend)
        calibration = calibration_provenance(backend, [pub[0] for pub in pubs])
        compile_seconds = time.perf_counter() - started
        return {
            "config": asdict(config), "register_name": reg_name,
            "metadata": {
                "mode": f"hardware ({backend.name})", "M": config.M, "N": config.N,
                "use_qec": config.use_qec, "thetas": list(config.thetas),
                "theta_samples": theta_samples, "p_list": config.p_list, "alpha": config.alpha,
                "shots": self.shots, "backend": backend.name,
                "optimization_level": self.optimization_level,
                "seed_transpiler": self.seed_transpiler, "initial_layout": effective_layout,
                "receiver_delay_factors": receiver_delay_factors or [1] * config.N,
                "sweep_axis": "tau", "sweep_values": tau_values,
                "linear_feedforward": config.linear_feedforward, "outcomes_list": None,
                "outcome_selection": "all hardware measurement branches; no postselection",
                "requested_outcomes_list": config.outcomes_list,
                "dt": getattr(target, "dt", None), "software": software,
                "compiled_templates": templates, "compiled_pubs": compiled_pubs,
                # Bound QPY avoids the installed SDK's symbolic-delay QPY
                # round-trip failure and reproduces the actual submitted ISA.
                "compiled_circuits": [circuit_provenance(pub[0], target) for pub in pubs],
                "compilation": compile_modes, "calibration": calibration,
                "execution": {"compile_seconds": compile_seconds},
                "timestamp": datetime.now().isoformat(),
            },
        }

    @staticmethod
    def replay_prepared(prepared: dict) -> list:
        """Restore the exact archived QPY and bindings; never retranspile."""
        import base64
        import hashlib
        import io
        from qiskit import qpy

        metadata = prepared["metadata"]
        if "compiled_circuits" in metadata:
            circuits = []
            for archived in metadata["compiled_circuits"]:
                payload = base64.b64decode(archived["qpy_base64"], validate=True)
                if hashlib.sha256(payload).hexdigest() != archived["sha256"]:
                    raise ValueError("Prepared circuit QPY checksum mismatch.")
                circuits.append(qpy.load(io.BytesIO(payload))[0])
            return circuits
        templates = []
        for template in metadata["compiled_templates"]:
            payload = base64.b64decode(template["qpy_base64"], validate=True)
            if hashlib.sha256(payload).hexdigest() != template["sha256"]:
                raise ValueError("Prepared circuit QPY checksum mismatch.")
            templates.append(qpy.load(io.BytesIO(payload))[0])
        circuits = []
        for pub in metadata["compiled_pubs"]:
            circuit = templates[pub["template_index"]]
            bindings = {parameter: pub["bindings"][parameter.name]
                        for parameter in circuit.parameters}
            circuits.append(circuit.assign_parameters(bindings))
        return circuits

    @staticmethod
    def collect_prepared(prepared: dict, result_container, *, job_id: str,
                         execution: dict | None = None) -> BroadcastResult:
        """Decode results in the archived canonical PUB order."""
        from copy import deepcopy
        from qiskit_ibm_runtime import RuntimeEncoder

        metadata = deepcopy(prepared["metadata"])
        metadata["prepared_at"] = metadata.get("prepared_at", metadata.get("timestamp"))
        execution = execution or {}
        # Plot dates identify submission, not compilation or retrieval. A
        # recovered receipt has only the durable attempt time; it is labelled
        # explicitly and never presented as actual device execution time.
        for field in ("submitted_at", "submission_time", "attempted_at", "collected_at"):
            if execution.get(field):
                metadata["timestamp"] = execution[field]
                metadata["timestamp_source"] = f"execution.{field}"
                break
        else:
            metadata["timestamp"] = datetime.now(timezone.utc).isoformat()
            metadata["timestamp_source"] = "result_collection_time"
        results = list(result_container)
        compiled_pubs = metadata["compiled_pubs"]
        if len(results) != len(compiled_pubs):
            raise ValueError(f"Expected {len(compiled_pubs)} PUB results, received {len(results)}.")
        n_theta = len(metadata["theta_samples"])
        n_tau = len(metadata["sweep_values"])
        def grid():
            return [[None] * n_tau for _ in range(n_theta)]
        fid_grid, counts_grid, sender_grid, invalid_grid, aligned_grid = [grid() for _ in range(5)]
        for index, pub_result in zip(compiled_pubs, results):
            ti, j = index["theta_index"], index["tau_index"]
            counts = dict(getattr(pub_result.data, prepared["register_name"]).get_counts())
            if sum(counts.values()) != metadata["shots"]:
                raise ValueError("Fidelity counts do not match the requested shots.")
            if any(len(bits) != metadata["N"] or set(bits) - {"0", "1"}
                   or not isinstance(count, (int, np.integer)) or count < 0
                   for bits, count in counts.items()):
                raise ValueError("Malformed fidelity histogram.")
            counts_grid[ti][j] = counts
            fid_grid[ti][j] = HardwareBackend._fidelities_from_counts(counts, metadata["N"])
            aligned_grid[ti][j] = HardwareBackend._aligned_shots(pub_result.data)
            if aligned_grid[ti][j]["available"] and aligned_grid[ti][j]["num_shots"] != metadata["shots"]:
                raise ValueError("Aligned register data do not match the requested shots.")
            if hasattr(pub_result.data, "m"):
                sender_grid[ti][j] = dict(pub_result.data.m.get_counts())
                if sum(sender_grid[ti][j].values()) != metadata["shots"]:
                    raise ValueError("Sender counts do not match the requested shots.")
                invalid_grid[ti][j] = HardwareBackend._compute_invalid_sender_rate(
                    sender_grid[ti][j], metadata["M"], metadata["N"])
        def runtime_json(value):
            return json.loads(json.dumps(value, cls=RuntimeEncoder))
        metadata.update({
            "job_id": job_id, "per_theta_fidelities": fid_grid if n_theta > 1 else None,
            "counts": counts_grid, "sender_counts": sender_grid,
            "invalid_sender_rate": invalid_grid, "aligned_shots": aligned_grid,
        })
        metadata["execution"].update(execution or {})
        metadata["execution"].update({
            "sampler_result_metadata": runtime_json(getattr(result_container, "metadata", None)),
            "pub_result_metadata": runtime_json([getattr(result, "metadata", None) for result in results]),
        })
        return BroadcastResult(
            fidelities=np.mean(np.asarray(fid_grid, dtype=float), axis=0).tolist(),
            metadata=metadata,
        )

    def run_tau_sweep(self, config: ProtocolConfig, tau_values, *, theta_samples=None,
                      receiver_delay_factors=None) -> BroadcastResult:
        """Compile, submit and wait for a sweep (legacy convenience interface).

        For recoverable experiments use the experiments CLI, which durably saves job
        IDs immediately and separates submission from result collection.
        """
        started = time.perf_counter()
        _validate_config(config)
        tau_values = self._validate_taus(tau_values)
        backend = self._backend()
        prepared = self.prepare_tau_sweep(
            config, tau_values, theta_samples=theta_samples,
            receiver_delay_factors=receiver_delay_factors, backend=backend,
        )
        sampler = self._sampler(backend)
        circuits = self.replay_prepared(prepared)
        submitted = datetime.now().isoformat()
        print(f"Submitting job with {len(circuits)} PUB(s)...")
        job = sampler.run([(circuit,) for circuit in circuits], shots=self.shots)
        print(f"Job ID: {job.job_id()}")
        results = job.result()
        return self.collect_prepared(prepared, results, job_id=job.job_id(), execution={
            "submission_time": submitted,
            "total_elapsed_seconds": time.perf_counter() - started,
            "sampler_options": _sampler_settings(sampler),
        })
