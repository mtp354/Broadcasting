#!/usr/bin/env python
"""CLI entry-point for broadcasting protocol experiments.

Designed for both local use and SLURM array jobs on CUNY HPC.

Examples
--------
Local run (exact simulation, no QEC)::

    python -m hpc.run_experiment --mode exact --M 1 --N 2

SLURM array sweep over noise values (1 value per task)::

    sbatch --array=0-9 hpc/slurm_broadcast.sh

When ``SLURM_ARRAY_TASK_ID`` is set the script selects one noise value
from ``--p-values`` or the evenly spaced ``--p-min/--p-max/--p-steps`` grid.
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np

# Ensure project root is importable when run from hpc/ directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from broadcasting.protocol import ProtocolConfig  # noqa: E402
from broadcasting.backend import ExactBackend, SamplingBackend  # noqa: E402
from broadcasting.results import save_run  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run broadcasting protocol simulations.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--mode",
        choices=["exact", "sampling"],
        default="exact",
        help="Simulation mode.",
    )
    p.add_argument("--M", type=int, default=1, help="Number of senders.")
    p.add_argument("--N", type=int, default=2, help="Number of receivers.")
    p.add_argument(
        "--alpha",
        type=float,
        default=None,
        help="Input-state coefficient (default: 1/sqrt(2), matching ProtocolConfig).",
    )
    p.add_argument(
        "--thetas",
        type=float,
        nargs="+",
        default=None,
        help="Phase angles for each sender (space-separated).",
    )
    p.add_argument("--use-qec", action="store_true", help="Enable [[5,1,3]] QEC.")
    outcomes = p.add_mutually_exclusive_group()
    outcomes.add_argument(
        "--outcomes",
        type=int,
        nargs="+",
        default=None,
        help="Fixed sender measurement outcomes (space-separated).",
    )

    p.add_argument("--linear-feedforward", type=int, choices=[0, 1], default=1)
    outcomes.add_argument("--random-outcomes", action="store_true", help="Sample sender outcomes (default when --outcomes is absent).")
    p.add_argument("--experiment-id", default=None, help="Submission/campaign identity shared by array tasks.")

    # Noise sweep
    p.add_argument("--p-values", type=float, nargs="+", help="Explicit probability grid; takes precedence over min/max/steps.")
    p.add_argument("--p-min", type=float, default=0.0, help="Min noise probability.")
    p.add_argument("--p-max", type=float, default=1.0, help="Max noise probability.")
    p.add_argument("--p-steps", type=int, default=50, help="Number of noise steps.")

    # Sampling options
    p.add_argument(
        "--n-samples",
        type=int,
        default=1000,
        help="Monte Carlo samples (sampling mode only).",
    )
    p.add_argument("--seed", type=int, default=None, help="RNG seed.")

    # Output
    p.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="Directory to write result JSON.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    p_full = np.asarray(args.p_values if args.p_values is not None else
                        np.linspace(args.p_min, args.p_max, args.p_steps), dtype=float)
    if not len(p_full) or not np.all(np.isfinite(p_full)) or np.any((p_full < 0) | (p_full > 1)):
        raise ValueError("Probability grid must be nonempty, finite, and in [0, 1].")
    if len(set(p_full.tolist())) != len(p_full):
        raise ValueError("Probability grid must not contain duplicate points.")

    # SLURM array support: select a single noise value if running as an
    # array task, otherwise sweep all values.
    task_id = os.environ.get("SLURM_ARRAY_TASK_ID")
    if task_id is not None:
        idx = int(task_id)
        if idx < 0 or idx >= len(p_full):
            print(f"SLURM_ARRAY_TASK_ID={idx} out of range (max {len(p_full)-1})")
            sys.exit(1)
        p_list = [float(p_full[idx])]
    else:
        p_list = p_full.tolist()

    alpha = args.alpha if args.alpha is not None else 1.0 / np.sqrt(2)

    if args.thetas is not None:
        thetas = args.thetas
    else:
        thetas = [np.pi / 4] * args.M

    config = ProtocolConfig(
        M=args.M,
        N=args.N,
        alpha=alpha,
        thetas=thetas,
        p_list=p_list,
        use_qec=args.use_qec,
        outcomes_list=args.outcomes,
        n_samples=args.n_samples if args.mode == "sampling" else None,
        seed=args.seed,
        linear_feedforward=bool(args.linear_feedforward),
    )

    if args.mode == "exact":
        backend = ExactBackend()
    else:
        backend = SamplingBackend(n_samples=args.n_samples, seed=args.seed)

    print(f"Running {args.mode} simulation  M={args.M} N={args.N} "
          f"QEC={args.use_qec}  p_list length={len(p_list)}")

    result = backend.run(config)

    result.metadata.update({
        "experiment_id": args.experiment_id or os.environ.get("SLURM_ARRAY_JOB_ID") or os.environ.get("SLURM_JOB_ID"),
        "requested_sweep_values": p_full.tolist(),
        "sweep_task_index": int(task_id) if task_id is not None else None,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_array_job_id": os.environ.get("SLURM_ARRAY_JOB_ID"),
    })

    out_path = save_run(result, config, results_dir=args.output_dir)
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
