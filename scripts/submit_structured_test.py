"""Preliminary hardware comparison: generic vs. structured broadcasting circuits.

Compares the existing generic-isometry circuit (``qc.initialize`` +
exponential ``(N+1)**M``-branch feedforward) against the new structured
circuit (Dicke-state prep + linear bit-conditioned feedforward, see
ACTION_PLAN.md Phase 6) for small, cheap configurations, *without* QEC (the
[[5,1,3]] decoder redesign is a separate, not-yet-completed follow-up).

This script never submits to hardware unless you explicitly pass ``--submit``.
By default it only prints local gate-count/depth comparisons and validates
both circuits give near-unit fidelity in noiseless Aer simulation, so you can
sanity check everything before spending real device time.

Usage
-----
Local-only sanity check (no IBM account needed)::

    python scripts/submit_structured_test.py

Actually submit both circuit variants to a real backend (uses your saved
``QiskitRuntimeService`` account)::

    python scripts/submit_structured_test.py --submit --backend ibm_kingston --shots 2000

Add ``--configs 1,2 2,2`` to choose different (M,N) pairs (format ``M,N``,
space-separated; N must be 1 or 2 since that's what structured prep supports).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from broadcasting.circuit import generate_qiskit_circuit
from broadcasting.fidelity import add_fidelity
from broadcasting.protocol import ProtocolConfig
from broadcasting.backend import HardwareBackend
from broadcasting.results import save_run


def _parse_configs(raw: list[str]) -> list[tuple[int, int]]:
    configs = []
    for item in raw:
        m_str, n_str = item.split(",")
        m, n = int(m_str), int(n_str)
        if n not in (1, 2):
            raise ValueError(
                f"N={n} not supported by structured prep yet (only N in {{1,2}})."
            )
        configs.append((m, n))
    return configs


def _build_variant(M: int, N: int, theta: float, alpha: float, *, structured: bool):
    """Build one (generic or structured) circuit + append fidelity readout."""
    qc = generate_qiskit_circuit(
        M, N, [theta] * M, alphas=alpha, tau=0,
        use_receiver_qec_513=False,
        use_structured_prep=structured,
        linear_feedforward=structured,  # pair structured-prep with linear feedforward
    )
    qc, reg_name, _ = add_fidelity(qc, N=N, thetas=[theta] * M, alpha=alpha)
    return qc, reg_name


def _local_report(M: int, N: int, theta: float, alpha: float, backend_for_transpile=None) -> None:
    from qiskit_aer import AerSimulator

    print(f"\n=== M={M}, N={N} ===")
    for label, structured in (("generic", False), ("structured", True)):
        qc, reg_name = _build_variant(M, N, theta, alpha, structured=structured)

        sim = AerSimulator(method="automatic")
        result = sim.run(qc, shots=4096, seed_simulator=0).result()
        counts = result.get_counts()
        total = sum(counts.values())
        fids = [
            sum(c for bs, c in counts.items() if bs.split()[0][N - 1 - i] == "0") / total
            for i in range(N)
        ]

        depth_info = ""
        if backend_for_transpile is not None:
            from qiskit.transpiler import generate_preset_pass_manager

            pm = generate_preset_pass_manager(backend=backend_for_transpile, optimization_level=3)
            isa = pm.run([qc])[0]
            ops = isa.count_ops()
            two_q = sum(v for k, v in ops.items() if k in ("cx", "cz", "ecr", "rzz"))
            depth_info = f", transpiled depth={isa.depth()}, 2q-gates~{two_q}"

        print(
            f"  {label:10s}: qubits={qc.num_qubits}, depth={qc.depth()}, "
            f"fidelities={[f'{f:.3f}' for f in fids]}{depth_info}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--configs", nargs="+", default=["1,1", "1,2"], help="M,N pairs to test.")
    parser.add_argument("--theta", type=float, default=0.4, help="Sender angle (same for all senders).")
    parser.add_argument("--alpha", type=float, default=1 / np.sqrt(2), help="Target-state alpha.")
    parser.add_argument("--submit", action="store_true", help="Actually submit to IBM hardware.")
    parser.add_argument("--backend", type=str, default=None, help="Backend name (required with --submit).")
    parser.add_argument("--shots", type=int, default=2000, help="Shots per circuit if --submit.")
    parser.add_argument("--optimization-level", type=int, default=3)
    parser.add_argument("--output-dir", type=str, default="results")
    args = parser.parse_args(argv)

    configs = _parse_configs(args.configs)

    print("Local sanity check (noiseless Aer simulation, no IBM account needed):")
    try:
        from qiskit_ibm_runtime.fake_provider import FakeBrisbane

        fake_backend = FakeBrisbane()
        print(f"(transpiling against {fake_backend.name} for a realistic gate-count comparison)")
    except Exception as exc:  # pragma: no cover - optional dependency path
        fake_backend = None
        print(f"(skipping transpiled gate-count comparison: {exc})")

    for M, N in configs:
        _local_report(M, N, args.theta, args.alpha, backend_for_transpile=fake_backend)

    if not args.submit:
        print("\nDone. Pass --submit --backend <name> to actually run on IBM hardware.")
        return

    if not args.backend:
        raise SystemExit("--backend is required with --submit.")

    from qiskit_ibm_runtime import QiskitRuntimeService

    service = QiskitRuntimeService()
    print(f"\nSubmitting to {args.backend} with {args.shots} shots per circuit...")

    for M, N in configs:
        for structured in (False, True):
            config = ProtocolConfig(
                M=M, N=N, alpha=args.alpha, thetas=[args.theta] * M,
                use_structured_prep=structured,
                linear_feedforward=structured,
            )
            backend = HardwareBackend(
                service=service,
                backend_name=args.backend,
                shots=args.shots,
                optimization_level=args.optimization_level,
            )
            result = backend.run(config)
            label = "structured" if structured else "generic"
            print(f"  M={M},N={N},{label}: job {result.metadata['job_id']}, "
                  f"fidelities={result.fidelities}")
            path = save_run(result, config, results_dir=args.output_dir)
            print(f"    saved to {path}")


if __name__ == "__main__":
    main()
