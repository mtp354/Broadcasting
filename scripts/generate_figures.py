#!/usr/bin/env python3
"""Generate manuscript figures from pinned saved inputs without collecting data.

    python scripts/generate_figures.py

The source inventory, historical overrides, and exact output stems live in
figures/sources.json. New convergence simulations require --collect-convergence;
that explicit collection step archives every measurement before rendering it.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from broadcasting.analysis import delay_axis
from broadcasting.convergence import (collect_convergence_repeats, load_historical_convergence, plot_convergence)
from broadcasting.plotting import plot_hardware_scaling, save_figure
from broadcasting.simulation import logical_error_polynomial
from scripts.figure_sources import figure_runs, source_manifest


def _save(fig, key, out_dirs, formats):
    if tuple(formats) != ("png",):
        raise ValueError("Figures are saved as PNG only.")
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


def generate_sampling_convergence(out_dirs, formats=("png",), *, archive_dir=None):
    """Restore historical summaries and overlay completed compatible seed runs."""
    if tuple(formats) != ("png",):
        raise ValueError("Convergence figures are PNG only.")
    study = load_historical_convergence(archive_dir=archive_dir)
    fig = plot_convergence(study)
    for directory in out_dirs:
        save_figure(fig, Path(directory) / "mc_sampling_convergence.png")
    return fig


def collect_sampling_convergence(out_dirs, *, quick=False, formats=("png",), collect=False, archive_dir=None):
    """Explicit local collection; the notebook exposes checkpoints and full settings."""
    if not collect:
        raise ValueError("Convergence requires explicit collection.")
    if tuple(formats) != ("png",):
        raise ValueError("Convergence figures are PNG only.")
    study = load_historical_convergence(archive_dir=archive_dir)
    counts = study.sample_counts[:5] if quick else study.sample_counts
    batch = collect_convergence_repeats(study, repeats=2, sample_counts=counts)
    generate_sampling_convergence(out_dirs, formats, archive_dir=study.archive_dir)
    return batch


def generate_qec_memory(out_dirs, formats=("png",)):
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


def generate_qec_crossover(out_dirs, formats=("png",)):
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


def generate_delay_sweeps(out_dirs, formats=("png",)):
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
        ax.set(xlabel=f"Idle delay time ({unit})", ylabel="Receiver fidelity", ylim=(0, 1.02))
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
        fig.tight_layout()
        _save(fig, key, out_dirs, formats)


def plot_hardware_tau0(runs):
    """Compatibility name for opt3 receiver-count scaling."""
    return plot_hardware_scaling(runs)


def generate_hardware_tau0(out_dirs, formats=("png",)):
    fig = plot_hardware_tau0(figure_runs("hardware_tau0"))
    return _save(fig, "hardware_tau0", out_dirs, formats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Generate all saved-data figures (default).")
    parser.add_argument("--formats", choices=["png"], default="png", help="PNG is the only supported figure format.")
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
        generate_sampling_convergence(out_dirs, formats)
    generate_qec_memory(out_dirs, formats)
    generate_qec_crossover(out_dirs, formats)
    generate_delay_sweeps(out_dirs, formats)
    generate_hardware_tau0(out_dirs, formats)


if __name__ == "__main__":
    main()
