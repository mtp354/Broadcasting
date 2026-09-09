#!/usr/bin/env python3
"""Generate manuscript figures from pinned saved inputs without collecting data.

    python scripts/generate_figures.py --formats png,pdf

The source inventory, historical overrides, and exact output stems live in
figures/sources.json. New convergence simulations require --collect-convergence;
that explicit collection step archives every measurement before rendering it.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from broadcasting.analysis import delay_axis, joint_success_statistics
from broadcasting.backend import ExactBackend, SamplingBackend
from broadcasting.plotting import save_figure
from broadcasting.protocol import ProtocolConfig
from broadcasting.provenance import software_provenance
from broadcasting.results import write_run_json
from broadcasting.simulation import logical_error_polynomial
from broadcasting.validation import dedupe_by_job
from scripts.figure_sources import figure_runs, source_manifest


def _save(fig, key, out_dirs, formats):
    if not out_dirs:
        return fig
    spec = source_manifest()["figures"][key]
    for directory in out_dirs:
        stem = spec["manuscript_output" if directory.name == "manuscript" else "figure_output"]
        for fmt in formats:
            path = save_figure(fig, directory / f"{stem}.{fmt}", strip_titles=True)
            print(f"Saved {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    plt.close(fig)
    return fig


def collect_sampling_convergence(out_dirs, *, quick=False, formats=("png", "pdf"), collect=False, archive_dir=None):
    """Explicitly collect, archive, and plot independent Monte Carlo repetitions.

    This function is deliberately gated: ordinary figure regeneration is read-only
    with respect to experimental records. Reuse of each seed across sample sizes
    makes a log-log fit descriptive, not an independent-error regression test.
    """
    if not collect:
        raise ValueError("Convergence requires explicit collection; the old multi-seed figure was withdrawn.")
    p_arr = np.linspace(0, 1, 21)
    config = ProtocolConfig(M=1, N=2, alpha=1 / np.sqrt(2), thetas=[0.0],
                            p_list=p_arr.tolist(), use_qec=True, outcomes_list=[0])
    exact = np.asarray(ExactBackend().run(config).fidelities)
    n_sweep = [50, 100, 200, 500, 1000] if quick else [50, 100, 200, 500, 1000, 2000, 5000]
    seeds = [0, 1, 2] if quick else [0, 1, 2, 3, 4]
    errors = np.zeros((len(seeds), len(n_sweep)))
    measurements = []
    for seed_index, seed in enumerate(seeds):
        for sample_index, samples in enumerate(n_sweep):
            effective = replace(config, seed=seed, n_samples=samples)
            sampled = SamplingBackend().run(effective)
            fids = np.asarray(sampled.fidelities)
            errors[seed_index, sample_index] = np.trapezoid(np.abs(fids - exact), p_arr, axis=0).sum()
            measurements.append({"seed": seed, "n_samples": samples,
                                 "execution_metadata": sampled.metadata,
                                 "fidelities": fids.tolist(),
                                 "error_area": float(errors[seed_index, sample_index])})
    archive_dir = Path(archive_dir) if archive_dir else ROOT / "results" / "convergence"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"convergence_{uuid.uuid4().hex}.json"
    write_run_json({"timestamp": datetime.now(timezone.utc).isoformat(), "config": asdict(config),
                    "software": software_provenance(),
                    "exact_fidelities": exact.tolist(), "seeds": seeds, "sample_counts": n_sweep,
                    "measurements": measurements,
                    "fit_scope": "Descriptive log-log OLS; shared seeds correlate sample-size estimates. Exponent uncertainty is not estimated."}, archive)
    print(f"Archived convergence measurements: {archive}")
    means, deviations = errors.mean(axis=0), errors.std(axis=0, ddof=1)
    slope, intercept = np.polyfit(np.log(n_sweep), np.log(means), 1)
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.errorbar(n_sweep, means, yerr=deviations, fmt="o", capsize=3,
                label=f"{len(seeds)} distinct effective seeds, mean ± sample SD")
    ax.plot(n_sweep, np.exp(intercept) * np.asarray(n_sweep) ** slope, "k--",
            label=f"Descriptive fit: $n^{{{slope:.3f}}}$")
    ax.set(xscale="log", yscale="log", xlabel="Number of trajectories", ylabel="Integrated absolute fidelity error")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    for directory in out_dirs:
        for fmt in formats:
            save_figure(fig, directory / f"sampling_convergence_new.{fmt}")
    plt.close(fig)
    return archive


def generate_qec_memory(out_dirs, formats=("png", "pdf")):
    """Four historical Kingston memory curves with explicit encoded/bare provenance."""
    runs = figure_runs("qec_memory")
    ref = runs[0]
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    scale, unit = delay_axis(ref)
    ax.plot(scale * np.asarray(ref["tau_values"]), ref["ideal_fidelities"], "k--", linewidth=1.2, label="Noise-free")
    for run in runs:
        run_scale, run_unit = delay_axis(run)
        if run_unit != unit:
            raise ValueError("Memory curves must use common, explicitly supported delay units.")
        qec = "Encoded" if run["use_qec"] else "Bare"
        date = run["timestamp"][:10]
        ax.plot(run_scale * np.asarray(run["tau_values"]), run["backend_fidelities"], linewidth=1.2,
                label=f"{qec}, opt={run['optimization_level']}, {date}")
    ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5)
    ax.set(xlabel=f"Delay time ({unit})", ylabel="Recovered-state fidelity", ylim=(0, 1.05))
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, "qec_memory", out_dirs, formats)


def generate_qec_crossover(out_dirs, formats=("png", "pdf")):
    """Exact and sampled curves on their own saved grids with a small-p inset."""
    runs = figure_runs("qec_crossover")
    for run in runs:
        if run["M"] != 1 or run["N"] != 2 or run["sweep"]["axis"] != "p":
            raise ValueError("Crossover source has the wrong protocol or sweep axis.")
        if not np.isclose(run["alpha"], runs[0]["alpha"]) or not np.allclose(run["theta_samples"], runs[0]["theta_samples"]):
            raise ValueError("Crossover sources must have matching alpha and theta settings.")
    p_fine = np.linspace(0, 1, 500)
    p_star = (3 - np.sqrt(6)) / 4
    fig, ax = plt.subplots(figsize=(6.8, 4.5))
    inset = ax.inset_axes([0.60, 0.54, 0.37, 0.40])
    for axis in [ax, inset]:
        axis.plot(p_fine, 1 - 2 * p_fine / 3, "k--", linewidth=1.1, label="Bare theory")
        axis.plot(p_fine, 1 - 2 * logical_error_polynomial(p_fine) / 3, "r-", linewidth=1.2, label="Encoded theory")
        labels = ["Exact bare", "Exact encoded", f"Sampled encoded ($n_s={runs[2]['n_samples']}$)"]
        for run, marker, color, label in zip(runs, ["o", "s", "^"], ["black", "red", "tab:purple"], labels):
            x = np.asarray(run["sweep"]["values"])
            y = np.asarray(run["fidelities"]).mean(axis=1)
            if x.shape != y.shape:
                raise ValueError("Crossover source grid and fidelity lengths differ.")
            axis.plot(x, y, marker, color=color, markersize=3.5, label=label)
        axis.axvline(p_star, color="gray", linestyle=":")
        axis.grid(alpha=0.2)
    inset.set(xlim=(0, 0.20), ylim=(0.84, 1.01))
    inset.tick_params(labelsize=7)
    ax.set(xlabel="Depolarizing probability $p$", ylabel="Receiver fidelity $F$", xlim=(0, 1), ylim=(0.3, 1.02))
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    return _save(fig, "qec_crossover", out_dirs, formats)


def generate_delay_sweeps(out_dirs, formats=("png", "pdf")):
    for key in ["delay_opt3", "delay_opt0"]:
        run = figure_runs(key)[0]
        scale, unit = delay_axis(run)
        tau = scale * np.asarray(run["sweep"]["values"])
        fids = np.asarray(run["fidelities"])
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        for i in range(run["N"]):
            ax.plot(tau, fids[:, i], linewidth=1.2, label=f"Receiver {i + 1}")
        ax.plot(tau, fids.mean(axis=1), "k--", linewidth=1.2, label="Average")
        ax.axhline(0.5, color="gray", linestyle=":", alpha=0.5)
        ax.set(xlabel=f"Idle delay time ({unit})", ylabel="Fidelity $P(0)$", ylim=(0.4, 1.02))
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        _save(fig, key, out_dirs, formats)


def plot_hardware_tau0(runs):
    """Display separate per-job/theta points; receiver spread is not an error bar."""
    points = []
    for run in dedupe_by_job(runs):
        if run.get("experiment_type") != "hardware" or run.get("sweep", {}).get("axis") != "tau":
            continue
        values = np.asarray(run["sweep"]["values"])
        indices = np.flatnonzero(values == 0)
        if len(indices) != 1 or not run.get("counts"):
            continue
        for theta_index, row in enumerate(run["counts"]):
            stats = joint_success_statistics(row[int(indices[0])], run["N"])
            points.append((run, theta_index, stats))
    if not points:
        raise ValueError("No saved joint receiver counts at tau=0.")
    points.sort(key=lambda p: (p[0]["backend"], p[0]["timestamp"], p[1]))
    fig, ax = plt.subplots(figsize=(8.5, max(4.0, len(points) * 0.36)))
    colors = dict(zip(sorted({r["backend"] for r, _, _ in points}), plt.cm.tab10.colors))
    labels, seen = [], set()
    for y, (run, theta, stats) in enumerate(points):
        local = stats["local_fidelities"]
        backend = run["backend"]
        color = colors[backend]
        ax.plot([min(local), max(local)], [y, y], color=color, linewidth=2, alpha=0.65)
        ax.scatter(stats["mean_local"]["estimate"], y, color=color, s=24,
                   label=backend if backend not in seen else "_nolegend_")
        ax.scatter(stats["worst_receiver"]["estimate"], y, color=color, marker="|", s=90)
        seen.add(backend)
        label = (f"{run['timestamp'][5:10]} {run['timestamp'][11:19]}  M{run['M']} N{run['N']}  "
                 f"opt{run['optimization_level']}  {stats['shots']} shots  θ{theta}")
        campaign = (run.get("metadata") or {}).get("campaign")
        if campaign:
            label = (f"repeat {campaign['repeat_index']} / {campaign['case_id']}  "
                     f"M{run['M']} N{run['N']}  θ{theta}")
        labels.append(label)
    ax.set_yticks(range(len(points)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.axvline(0.5, color="gray", linestyle=":", alpha=0.5)
    ax.set(xlabel="Receiver fidelity at τ=0: mean (dot), receiver range (line)", xlim=(0.3, 1.02))
    ax.grid(axis="x", alpha=0.25)
    ax.legend(fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3)
    fig.tight_layout()
    return fig


def generate_hardware_tau0(out_dirs, formats=("png", "pdf")):
    fig = plot_hardware_tau0(figure_runs("hardware_tau0"))
    return _save(fig, "hardware_tau0", out_dirs, formats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Generate all saved-data figures (default).")
    parser.add_argument("--formats", default="png,pdf")
    parser.add_argument("--collect-convergence", action="store_true", help="Explicitly collect NEW simulation measurements and archive them.")
    parser.add_argument("--quick", action="store_true", help="Shorter sample-size grid, only with --collect-convergence.")
    args = parser.parse_args()
    if args.quick and not args.collect_convergence:
        parser.error("--quick applies only to explicit --collect-convergence.")
    formats = tuple(f.strip() for f in args.formats.split(","))
    out_dirs = [ROOT / "manuscript", ROOT / "figures"]
    if args.collect_convergence:
        collect_sampling_convergence(out_dirs, quick=args.quick, formats=formats, collect=True)
    else:
        print("Convergence figure withdrawn: no independent saved measurements; collection is disabled.")
    generate_qec_memory(out_dirs, formats)
    generate_qec_crossover(out_dirs, formats)
    generate_delay_sweeps(out_dirs, formats)
    generate_hardware_tau0(out_dirs, formats)


if __name__ == "__main__":
    main()
