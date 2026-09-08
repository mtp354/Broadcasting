#!/usr/bin/env python3
"""generate_figures.py -- Reproducible figure generation pipeline.

Generates all manuscript and paper figures directly from authoritative saved JSON
records in results/ and results/qec513/. Strips plot titles by default and exports
in both PNG and vector PDF formats to manuscript/ and figures/.

Usage
-----
    python scripts/generate_figures.py [--all] [--quick] [--formats png,pdf]
"""

import argparse
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

# Ensure project root is in python path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from broadcasting.backend import ExactBackend, SamplingBackend
from broadcasting.plotting import save_figure
from broadcasting.protocol import ProtocolConfig
from broadcasting.results import list_runs, load_run
from broadcasting.simulation import logical_error_polynomial
from broadcasting.validation import dedupe_by_job, group_by_cohort


def generate_figure_1_convergence(
    out_dirs: list[Path],
    *,
    quick: bool = False,
    formats: tuple[str, ...] = ("png", "pdf"),
) -> None:
    """Figure 1: Monte Carlo sampling error convergence with fitted exponent."""
    print("\n--- Generating Figure 1: MC Sampling Convergence ---")
    p_arr = np.linspace(0, 1, 21)
    conv_config = ProtocolConfig(
        M=1,
        N=2,
        alpha=1.0 / np.sqrt(2),
        thetas=[0.0],
        p_list=p_arr.tolist(),
        use_qec=True,
        outcomes_list=[0],
        seed=0,
    )

    exact_fids = np.asarray(ExactBackend().run(conv_config).fidelities)

    n_sweep = [50, 100, 200, 500, 1000] if quick else [50, 100, 200, 500, 1000, 2000, 5000]
    seeds = [0, 1, 2] if quick else [0, 1, 2, 3, 4]

    errors = np.zeros((len(seeds), len(n_sweep)))
    for si, seed in enumerate(seeds):
        for ni, ns in enumerate(n_sweep):
            sampled = SamplingBackend(n_samples=ns, seed=seed).run(conv_config)
            diff = np.abs(np.asarray(sampled.fidelities) - exact_fids)
            errors[si, ni] = np.trapezoid(diff, p_arr, axis=0).sum()

    mean_errors = errors.mean(axis=0)
    std_errors = errors.std(axis=0)

    log_n = np.log(n_sweep)
    log_err = np.log(mean_errors)
    slope, intercept = np.polyfit(log_n, log_err, 1)
    residuals = log_err - (slope * log_n + intercept)
    dof = len(n_sweep) - 2
    slope_se = (
        np.sqrt(np.sum(residuals**2) / dof / np.sum((log_n - log_n.mean()) ** 2))
        if dof > 0
        else float("nan")
    )
    print(f"  Fitted exponent: {slope:.3f} +/- {slope_se:.3f} (theoretical -0.5)")

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.errorbar(
        n_sweep,
        mean_errors,
        yerr=std_errors,
        fmt="o",
        color="tab:blue",
        capsize=3,
        label=f"Observed ({len(seeds)} seeds, mean +/- std)",
    )
    fit_line = np.exp(intercept) * np.asarray(n_sweep, dtype=float) ** slope
    ax.plot(
        n_sweep,
        fit_line,
        "--",
        color="black",
        linewidth=1.2,
        label=f"Fit: $n^{{{slope:.3f} \\pm {slope_se:.3f}}}$",
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Number of trajectories $n_s$")
    ax.set_ylabel("Error area $\\int |F_\\mathrm{sampled} - F_\\mathrm{exact}|\\,dp$")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(framealpha=0.9)
    plt.tight_layout()

    for d in out_dirs:
        for fmt in formats:
            fname = "mc_sampling_convergence" if d.name == "manuscript" else "sampling_convergence"
            save_figure(fig, d / f"{fname}.{fmt}", strip_titles=True)
            print(f"  Saved -> {d / f'{fname}.{fmt}'}")
    plt.close(fig)


def generate_figure_2_qec_memory(
    out_dirs: list[Path],
    formats: tuple[str, ...] = ("png", "pdf"),
) -> None:
    """Figure 2: [[5,1,3]] standalone memory benchmark."""
    print("\n--- Generating Figure 2: QEC Encoded Memory Benchmark ---")
    qec_dir = ROOT / "results" / "qec513"
    qec_files = sorted(qec_dir.glob("qec513_delay_sweep_*.json"))
    if not qec_files:
        print("  Warning: No QEC files found in results/qec513/")
        return

    saved = []
    seen_jobs = {}
    for p in qec_files:
        with open(p) as f:
            rec = json.load(f)
        jid = rec.get("job_id")
        if jid and jid in seen_jobs:
            continue
        if jid:
            seen_jobs[jid] = p.name
        saved.append(rec)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ref = saved[0]
    scale = 4e-3
    x_ref = scale * np.asarray(ref["tau_values"], dtype=float)
    ax.plot(x_ref, ref["ideal_fidelities"], color="tab:green", linewidth=1.5, label="Noise-free")

    colors = plt.cm.tab10.colors
    for i, run in enumerate(saved):
        tau = scale * np.asarray(run["tau_values"], dtype=float)
        opt = run.get("optimization_level", "?")
        backend = run.get("backend", "ibm_hardware")
        shots = run.get("shots", "?")
        label = f"{backend} opt={opt} ({shots} shots)"
        ax.plot(tau, run["backend_fidelities"], color=colors[i % len(colors)], linewidth=1.2, label=label)

    ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5, label="Random guessing (0.5)")
    ax.set_xlabel("Delay time ($\\mu$s)")
    ax.set_ylabel("Logical State Fidelity")
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="best")
    plt.tight_layout()

    for d in out_dirs:
        for fmt in formats:
            fname = "qec fidelity" if d.name == "manuscript" else "qec513_saved_sweeps"
            save_figure(fig, d / f"{fname}.{fmt}", strip_titles=True)
            print(f"  Saved -> {d / f'{fname}.{fmt}'}")
    plt.close(fig)


def generate_figure_4_qec_crossover(
    out_dirs: list[Path],
    formats: tuple[str, ...] = ("png", "pdf"),
) -> None:
    """Figure 4: QEC crossover comparison with exact, sampled, and closed-form curves."""
    print("\n--- Generating Figure 4: QEC Crossover ---")
    runs = list_runs(ROOT / "results")

    def find_run(use_qec: bool, backend: str):
        for r in runs:
            if (
                r.get("experiment_type") == "simulation"
                and r.get("M") == 1
                and r.get("N") == 2
                and bool(r.get("use_qec")) == use_qec
                and r.get("backend") == backend
                and r.get("sweep", {}).get("axis") == "p"
            ):
                return r
        return None

    run_no_qec = find_run(False, "aer_exact")
    run_qec_exact = find_run(True, "aer_exact")
    run_qec_samp = find_run(True, "aer_sampling")

    if not (run_no_qec and run_qec_exact):
        print("  Warning: Missing simulation runs for QEC crossover in results/")
        return

    p_vals = np.asarray(run_no_qec["sweep"]["values"], dtype=float)
    fid_no_qec = np.asarray(run_no_qec["fidelities"], dtype=float).mean(axis=1)
    fid_qec_exact = np.asarray(run_qec_exact["fidelities"], dtype=float).mean(axis=1)
    fid_qec_samp = (
        np.asarray(run_qec_samp["fidelities"], dtype=float).mean(axis=1)
        if run_qec_samp
        else None
    )

    # Analytical curves
    p_fine = np.linspace(0, 1, 200)
    f_bare_theory = 1.0 - (2.0 / 3.0) * p_fine
    f_qec_theory = 1.0 - (2.0 / 3.0) * np.array([logical_error_polynomial(p) for p in p_fine])
    p_star = (3.0 - np.sqrt(6.0)) / 4.0

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(p_fine, f_bare_theory, "k--", linewidth=1.2, label="Bare theoretical $1 - 2p/3$")
    ax.plot(p_fine, f_qec_theory, "r-", linewidth=1.5, label="QEC theoretical $1 - \\frac{2}{3}p_L(p)$")
    ax.plot(p_vals, fid_no_qec, "o", color="black", markersize=4, label="Exact bare (simulation)")
    ax.plot(p_vals, fid_qec_exact, "s", color="red", markersize=4, label="Exact QEC (simulation)")
    if fid_qec_samp is not None:
        ax.plot(p_vals, fid_qec_samp, "^", color="tab:purple", markersize=4, label="Sampled QEC ($n_s=1000$)")

    ax.axvline(p_star, color="gray", linestyle=":", label=f"$p^* \\approx {p_star:.4f}$")
    ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5)

    ax.set_xlabel("Depolarizing probability $p$")
    ax.set_ylabel("Receiver fidelity $F$")
    ax.set_xlim(0, 1)
    ax.set_ylim(0.3, 1.02)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="best")
    plt.tight_layout()

    for d in out_dirs:
        for fmt in formats:
            fname = "qec vs no qec vs sampling" if d.name == "manuscript" else "qec_crossover"
            save_figure(fig, d / f"{fname}.{fmt}", strip_titles=True)
            print(f"  Saved -> {d / f'{fname}.{fmt}'}")
    plt.close(fig)


def generate_figure_5_delay_sweeps(
    out_dirs: list[Path],
    formats: tuple[str, ...] = ("png", "pdf"),
) -> None:
    """Figure 5: Hardware idle delay sweeps on IBM Kingston."""
    print("\n--- Generating Figure 5: Hardware Delay Sweeps ---")
    files = {
        "opt3": ROOT / "results" / "run_20260518_120232.json",
        "opt0": ROOT / "results" / "run_20260518_122119.json",
    }

    scale = 4e-3  # us / dt

    for opt_key, fpath in files.items():
        if not fpath.exists():
            print(f"  Warning: {fpath.name} not found.")
            continue
        run = load_run(fpath)
        tau_dt = np.asarray(run["sweep"]["values"], dtype=float)
        tau_us = tau_dt * scale
        fids = np.asarray(run["fidelities"], dtype=float)

        fig, ax = plt.subplots(figsize=(7, 4.5))
        for r_idx in range(fids.shape[1]):
            ax.plot(tau_us, fids[:, r_idx], "-", linewidth=1.2, label=f"Receiver {r_idx + 1}")
        ax.plot(tau_us, fids.mean(axis=1), "k--", linewidth=1.5, label="Average")

        ax.axhline(0.5, color="gray", linestyle=":", alpha=0.5, label="Random (0.5)")
        ax.set_xlabel("Idle delay time ($\\mu$s)")
        ax.set_ylabel("Fidelity $P(0)$")
        ax.set_ylim(0.4, 1.02)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=9, loc="best")
        plt.tight_layout()

        for d in out_dirs:
            for fmt in formats:
                fname = f"delay time vs fidelity 121 {opt_key}" if d.name == "manuscript" else f"delay_sweep_121_{opt_key}"
                save_figure(fig, d / f"{fname}.{fmt}", strip_titles=True)
                print(f"  Saved -> {d / f'{fname}.{fmt}'}")
        plt.close(fig)


def generate_figure_6_scaling(
    out_dirs: list[Path],
    formats: tuple[str, ...] = ("png", "pdf"),
) -> None:
    """Figure 6: Hardware fidelity scaling at tau=0 across network sizes."""
    print("\n--- Generating Figure 6: Hardware Scaling at tau=0 ---")
    runs = list_runs(ROOT / "results")
    hw_runs = [r for r in runs if r.get("experiment_type") == "hardware"]
    hw_runs = dedupe_by_job(hw_runs)

    cohorts = group_by_cohort(hw_runs, keys=("backend", "shots"))
    print("  Stratified hardware cohorts:")
    for key, group in sorted(cohorts.items(), key=lambda kv: str(kv[0])):
        print(f"    {key}: {len(group)} run(s)")

    points = []
    for r in hw_runs:
        sweep_vals = np.asarray(r.get("sweep", {}).get("values", []), dtype=float)
        if sweep_vals.size == 0:
            continue
        z_idx = int(np.argmin(np.abs(sweep_vals)))
        if abs(sweep_vals[z_idx]) > 1e-9:
            continue
        fids = np.asarray(r["fidelities"][z_idx], dtype=float)
        points.append(
            (
                r["M"],
                r["N"],
                r.get("backend", "unknown"),
                float(fids.mean()),
                float(fids.min()),
                float(fids.max()),
            )
        )

    if not points:
        print("  Warning: No tau=0 hardware points found.")
        return

    fig, ax = plt.subplots(figsize=(6.8, 4.5))
    m_values = sorted({p[0] for p in points})
    backend_values = sorted({p[2] for p in points})

    m_colors = {
        m: c
        for m, c in zip(
            m_values, plt.cm.tab10(np.linspace(0, 1, max(len(m_values), 2)))
        )
    }
    backend_markers = {
        b: mk for b, mk in zip(backend_values, ["o", "s", "^", "D", "v", "P"])
    }

    seen_labels = set()
    n_values = sorted({p[1] for p in points})
    for M, N, backend, mean_fid, min_fid, max_fid in sorted(points):
        label = f"$M={M}$, {backend}"
        show_label = label not in seen_labels
        seen_labels.add(label)

        ax.errorbar(
            N,
            mean_fid,
            yerr=[[mean_fid - min_fid], [max_fid - mean_fid]],
            fmt=backend_markers[backend],
            color=m_colors[M],
            markeredgecolor="black",
            markersize=7,
            capsize=4,
            linewidth=1.2,
            label=label if show_label else "_nolegend_",
        )
        ax.scatter(N, min_fid, color=m_colors[M], marker="_", s=120, linewidths=2)

    ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Number of receivers ($N$)")
    ax.set_ylabel("Receiver fidelity at $\\tau=0$ (mean, spread, worst-case --)")
    ax.set_ylim(0.3, 1.02)
    ax.set_xticks(n_values)
    ax.set_xlim(min(n_values) - 0.5, max(n_values) + 0.5)
    ax.legend(title="Senders, Backend", fontsize=8, loc="upper right")
    ax.grid(alpha=0.25)
    plt.tight_layout()

    for d in out_dirs:
        for fmt in formats:
            fname = "fidelity scaling hardware" if d.name == "manuscript" else "hardware_tau0_scaling"
            save_figure(fig, d / f"{fname}.{fmt}", strip_titles=True)
            print(f"  Saved -> {d / f'{fname}.{fmt}'}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Generate publication figures with stripped titles.")
    parser.add_argument("--all", action="store_true", default=True, help="Generate all figures")
    parser.add_argument("--quick", action="store_true", help="Quick mode for convergence fitting")
    parser.add_argument("--formats", default="png,pdf", help="Comma-separated formats (e.g. png,pdf)")
    args = parser.parse_args()

    fmts = tuple(f.strip() for f in args.formats.split(","))
    out_dirs = [ROOT / "manuscript", ROOT / "figures"]
    for d in out_dirs:
        d.mkdir(exist_ok=True)

    print("==========================================================")
    print("Broadcasting Protocol: Publication Figure Generation")
    print(f"Output directories: {[str(d) for d in out_dirs]}")
    print(f"Formats: {fmts}")
    print("==========================================================")

    generate_figure_1_convergence(out_dirs, quick=args.quick, formats=fmts)
    generate_figure_2_qec_memory(out_dirs, formats=fmts)
    generate_figure_4_qec_crossover(out_dirs, formats=fmts)
    generate_figure_5_delay_sweeps(out_dirs, formats=fmts)
    generate_figure_6_scaling(out_dirs, formats=fmts)

    print("\n==========================================================")
    print("All figures successfully regenerated without titles.")
    print("==========================================================")


if __name__ == "__main__":
    main()

