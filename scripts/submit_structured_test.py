"""Preliminary hardware comparison: generic vs. structured broadcasting circuits.

Compares the existing generic circuit (``qc.initialize`` + exponential
feedforward) against the new structured circuit (Dicke-state prep + linear
feedforward, see ACTION_PLAN.md Phase 6), without QEC. Structured prep only
supports N in {1, 2}.

This script never submits to hardware unless you pass ``--submit``. By default
it only runs a local noiseless Aer check.

Usage
-----
Local-only sanity check (no IBM account needed)::

    python scripts/submit_structured_test.py

Submit both circuit variants to the least-busy real backend::

    python scripts/submit_structured_test.py --submit --shots 2000
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


def _build_variant(M: int, N: int, theta: float, alpha: float, structured: bool):
    qc = generate_qiskit_circuit(M, N, [theta] * M, alphas=alpha, tau=0, use_structured_prep=structured)
    return add_fidelity(qc, N=N, thetas=[theta] * M, alpha=alpha)


def _local_report(M: int, N: int, theta: float, alpha: float) -> None:
    from qiskit_aer import AerSimulator

    print(f"\n=== M={M}, N={N} ===")
    for label, structured in (("generic", False), ("structured", True)):
        qc, reg_name, _ = _build_variant(M, N, theta, alpha, structured)

        counts = AerSimulator().run(qc, shots=4096, seed_simulator=0).result().get_counts()
        total = sum(counts.values())
        fids = [
            sum(c for bs, c in counts.items() if bs.split()[0][N - 1 - i] == "0") / total
            for i in range(N)
        ]
        print(f"  {label:10s}: qubits={qc.num_qubits}, depth={qc.depth()}, fidelities={[f'{f:.3f}' for f in fids]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--configs", nargs="+", default=["1,1", "1,2"], help="M,N pairs to test.")
    parser.add_argument("--theta", type=float, default=0.4, help="Sender angle (same for all senders).")
    parser.add_argument("--alpha", type=float, default=1 / np.sqrt(2), help="Target-state alpha.")
    parser.add_argument("--submit", action="store_true", help="Actually submit to IBM hardware.")
    parser.add_argument("--backend", type=str, default=None, help="Backend name (default: least busy).")
    parser.add_argument("--shots", type=int, default=2000, help="Shots per circuit if --submit.")
    parser.add_argument("--optimization-level", type=int, default=3)
    parser.add_argument("--output-dir", type=str, default="results")
    args = parser.parse_args(argv)

    configs = [tuple(int(v) for v in item.split(",")) for item in args.configs]

    print("Local sanity check (noiseless Aer simulation, no IBM account needed):")
    for M, N in configs:
        _local_report(M, N, args.theta, args.alpha)

    if not args.submit:
        print("\nDone. Pass --submit to actually run on IBM hardware.")
        return

    from qiskit_ibm_runtime import QiskitRuntimeService

    service = QiskitRuntimeService()

    for M, N in configs:
        for structured in (False, True):
            config = ProtocolConfig(
                M=M, N=N, alpha=args.alpha, thetas=[args.theta] * M,
                use_structured_prep=structured,
            )
            backend = HardwareBackend(
                service=service,
                backend_name=args.backend,
                shots=args.shots,
                optimization_level=args.optimization_level,
            )
            result = backend.run(config)
            label = "structured" if structured else "generic"
            print(f"  M={M},N={N},{label}: backend={result.metadata['backend']} "
                  f"job={result.metadata['job_id']} fidelities={result.fidelities}")
            print(f"    saved to {save_run(result, config, results_dir=args.output_dir)}")


if __name__ == "__main__":
    main()

