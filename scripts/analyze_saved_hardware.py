#!/usr/bin/env python3
"""Reanalyze existing receiver counts; no hardware access or new experiment data.

Writes per-theta/per-delay statistics, cohort summaries and a report under
analysis/hardware/ by default. Historical source overlays are explicit in
figures/sources.json and never modify results/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from broadcasting.analysis import delay_axis, joint_success_statistics, periodicity_summary
from broadcasting.plotting import save_figure
from broadcasting.results import list_runs
from broadcasting.validation import dedupe_by_job, find_duplicate_jobs
from scripts.figure_sources import load_source, source_manifest
from scripts.generate_figures import plot_hardware_tau0


def _point_record(run, theta_index, sweep_index, counts):
    return {"filename": run["filename"], "job_id": run["job_id"],
            "theta_index": theta_index, "sweep_index": sweep_index,
            "tau_dt": run["sweep"]["values"][sweep_index],
            **joint_success_statistics(counts, run["N"])}


def analyze(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = source_manifest()
    hardware = [r for r in list_runs(ROOT / "results") if r["experiment_type"] == "hardware"]
    duplicates = find_duplicate_jobs(hardware)
    hardware = dedupe_by_job(hardware)
    # Archive all available hardware runs, not only the figure's selected sources.
    hardware = [load_source(f"results/{r['filename']}", manifest=manifest)
                if f"results/{r['filename']}" in manifest["runs"] else r for r in hardware]
    points, summaries = [], []
    for run in hardware:
        run_points = []
        count_grid = run.get("counts")
        if not count_grid:
            raise ValueError(f"Missing counts in hardware record: {run['filename']}")
        if len(count_grid) != len(run["theta_samples"]):
            raise ValueError(f"Theta/count grid mismatch: {run['filename']}")
        for theta_index, row in enumerate(count_grid):
            if len(row) != len(run["sweep"]["values"]):
                raise ValueError(f"Sweep/count grid mismatch: {run['filename']}")
            for sweep_index, counts in enumerate(row):
                point = _point_record(run, theta_index, sweep_index, counts)
                run_points.append(point)
        # The saved receiver fidelities must agree with the archived joint counts.
        recalculated = np.asarray([p["local_fidelities"] for p in run_points]).reshape(
            len(count_grid), len(run["sweep"]["values"]), run["N"])
        if not np.allclose(recalculated.mean(axis=0), run["fidelities"], atol=1e-10, rtol=0):
            raise ValueError(f"Saved fidelities disagree with joint counts: {run['filename']}")
        periodicity = []
        for theta_index in range(len(count_grid)):
            trace_run = dict(run, fidelities=recalculated[theta_index].tolist())
            for receiver in [None, *range(run["N"])]:
                periodicity.append({"theta_index": theta_index, "trace": "receiver_mean" if receiver is None else f"receiver_{receiver}",
                                    **periodicity_summary(trace_run, receiver=receiver)})
        points.extend(run_points)
        spec = manifest["runs"].get(f"results/{run['filename']}", {})
        summaries.append({
            **{k: run.get(k) for k in ["filename", "timestamp", "job_id", "backend", "optimization_level", "shots", "M", "N", "alpha", "use_qec", "theta_samples"]},
            "sha256": hashlib.sha256(Path(run["filepath"]).read_bytes()).hexdigest(),
            "historical_provenance": run.get("historical_provenance", {}),
            "circuit_history": spec.get("circuit_history", "Compiled circuit history unavailable."),
            "record_count": len(run_points),
            "tau0": [p for p in run_points if p["tau_dt"] == 0],
            "periodicity": periodicity,
        })
    qec, qec_duplicates = [], {}
    jobs = {}
    for path in sorted((ROOT / "results/qec513").glob("*.json")):
        relative = str(path.relative_to(ROOT))
        run = load_source(relative, manifest=manifest) if relative in manifest["runs"] else json.loads(path.read_text())
        job = run["job_id"]
        if job in jobs:
            qec_duplicates.setdefault(job, [jobs[job]]).append(path.name)
            continue
        jobs[job] = path.name
        stats = [joint_success_statistics(counts, 1) for counts in run["backend_counts"]]
        if not np.allclose([s["global_fidelity"]["estimate"] for s in stats], run["backend_fidelities"], atol=1e-10, rtol=0):
            raise ValueError(f"Saved QEC fidelity disagrees with counts: {path.name}")
        trace = {"N": 1, "sweep": {"axis": "tau", "values": run["tau_values"]},
                 "fidelities": [[f] for f in run["backend_fidelities"]], "metadata": run.get("metadata", {})}
        qec.append({"filename": path.name, "job_id": job,
                    **{k: run.get(k) for k in ["backend", "optimization_level", "shots", "state_prep", "use_qec"]},
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "historical_provenance": run.get("historical_provenance", {}),
                    "points": [{"tau_dt": tau, **stat} for tau, stat in zip(run["tau_values"], stats)],
                    "periodicity": periodicity_summary(trace),
                    "scope": "One recovered-qubit readout; receiver-pair covariance is not defined."})
    summary = {"method": "Finite-shot statistics computed per job, theta, delay; no pooling across settings or dates.",
               "limitations": "Wilson and multinomial delta-method intervals condition on independent shots with fixed success probabilities. Device drift/shot autocorrelation and calibration variation are not quantified by historical histograms. Peak frequencies are exploratory; no significance or physical-noise attribution.",
               "broadcasting_jobs": len(hardware), "broadcasting_histograms": len(points),
               "qec_unique_jobs": len(qec), "duplicate_broadcasting_jobs": duplicates, "duplicate_qec_jobs": qec_duplicates,
               "runs": summaries, "memory_runs": qec}
    (output_dir / "points.json").write_text(json.dumps(points, indent=2, allow_nan=False) + "\n")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    fig = plot_hardware_tau0(hardware)
    for fmt in ["png", "pdf"]:
        save_figure(fig, output_dir / f"tau0_fidelities.{fmt}")
    plt.close(fig)
    _derived_joint_figure(summaries, output_dir)
    _write_report(summary, output_dir)
    print(f"Analyzed {len(hardware)} broadcasting jobs ({len(points)} histograms), {len(qec)} unique memory jobs.")
    print(f"Derived report: {output_dir / 'report.md'}")
    return summary


def _derived_joint_figure(runs, output_dir):
    fig, ax = plt.subplots(figsize=(8.0, 5.5))
    labels = []
    y = 0
    for run in runs:
        for point in run["tau0"]:
            for key, marker, color, label in [("global_fidelity", "o", "tab:blue", "Joint fidelity (Wilson 95%)"),
                                              ("worst_receiver", "s", "tab:orange", "Worst receiver (simultaneous 95%)")]:
                item = point[key]
                lo, hi = item.get("ci95", item.get("simultaneous_ci95"))
                value = item["estimate"]
                ax.errorbar(value, y, xerr=[[value - lo], [hi - value]], fmt=marker, color=color,
                            markersize=4, capsize=2, label=label if y == 0 else None)
            labels.append(f"{run['filename'][4:-5]} θ{point['theta_index']}")
            y += 1
    ax.set_yticks(range(y), labels, fontsize=7)
    ax.invert_yaxis()
    ax.set(xlim=(0, 1.02), xlabel="Fidelity at τ=0, per job and theta sample")
    ax.grid(axis="x", alpha=0.2)
    ax.legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    for fmt in ["png", "pdf"]:
        save_figure(fig, output_dir / f"joint_and_worst_tau0.{fmt}")
    plt.close(fig)


def _write_report(summary, output_dir):
    lines = ["# Reanalysis of existing hardware readouts", "",
             f"Derived from **{summary['broadcasting_jobs']} broadcasting jobs / {summary['broadcasting_histograms']} per-theta, per-delay histograms** and **{summary['qec_unique_jobs']} unique standalone memory jobs**. No new circuits, trajectories, or hardware jobs were collected. Raw JSON files were not changed.", "",
             "Reproduce with `.venv/bin/python scripts/analyze_saved_hardware.py`. `summary.json` records source hashes, run metadata, tau-zero estimates and every trace's spectral summary; `points.json` contains all broadcasting point estimates, confidence intervals, paired differences and covariances. `figures/sources.json` pins publication inputs and records historical attribution evidence.", "",
             "## Definitions and uncertainty", "",
             "Receiver success is the zero bit in its target-basis readout, using little-endian receiver ordering. Joint/global fidelity is the observed all-zero frequency; worst fidelity is the minimum receiver marginal. The product of marginals is reported separately and is not assumed equal to the observed joint probability. Mean-fidelity uncertainty includes the shot-level receiver covariances.", "",
             "Marginal and joint intervals are two-sided 95% Wilson score intervals. The worst-receiver interval takes the minimum bounds of Bonferroni-adjusted Wilson intervals, so receiver selection is accounted for approximately. Pair covariance and paired receiver differences use multinomial delta-method 95% intervals; these are asymptotic, unadjusted for comparisons over delays/pairs, and can degenerate at boundary counts. The covariance convention is E[Xi Xj] − E[Xi]E[Xj] in each empirical histogram.", "",
             "These intervals quantify finite-shot uncertainty conditional on fixed probabilities and independent shots within a histogram. They exclude calibration drift, temporal shot correlation, and job-to-job variation. Historical counts lack shot ordering, calibrated layouts, and circuit revisions, so that assumption cannot be verified. No counts are pooled across jobs, theta samples or delay points.", "",
             "Nonzero receiver-success covariance does not identify correlated physical noise. Shared preparation, feedforward, readout, and within-job drift can contribute; conversely, zero measured covariance does not rule out correlated noise in other bases.", "",
             "## Tau-zero broadcasting results", "",
             "Every point is shown separately. Dates/time in the source filename identify the run; theta index distinguishes multiple samples within a job. The receiver range in `tau0_fidelities.png` is receiver heterogeneity, not statistical uncertainty. `joint_and_worst_tau0.png` shows shot intervals.", "",
             "| Run / theta | Backend / opt / shots | M,N | Mean | Worst (95% interval) | Joint (95% interval) | Receiver range |", "|---|---|---|---:|---|---|---:|"]
    for run in summary["runs"]:
        for point in run["tau0"]:
            w, g = point["worst_receiver"], point["global_fidelity"]
            lines.append(f"| {run['filename'][4:-5]} / {point['theta_index']} | {run['backend']} / {run['optimization_level']} / {point['shots']} | {run['M']},{run['N']} | {point['mean_local']['estimate']:.4f} | {w['estimate']:.4f} [{w['simultaneous_ci95'][0]:.4f}, {w['simultaneous_ci95'][1]:.4f}] | {g['estimate']:.4f} [{g['ci95'][0]:.4f}, {g['ci95'][1]:.4f}] | {point['receiver_spread']:.4f} |")
    lines += ["", "## Pair covariance and receiver asymmetry", "",
              "The table gives every N=2 tau-zero pair, within a single theta/job, as estimate ± asymptotic SE. All other pairs/delays are retained in `points.json`. No multiplicity-adjusted significance claim is made.", "",
              "| Run / theta | Cov(success 0, success 1) | F0 − F1 |", "|---|---:|---:|"]
    for run in summary["runs"]:
        if run["N"] != 2:
            continue
        for point in run["tau0"]:
            pair = point["pairs"][0]
            c, d = pair["covariance"], pair["fidelity_difference"]
            lines.append(f"| {run['filename'][4:-5]} / {point['theta_index']} | {c['estimate']:.5f} ± {c['se']:.5f} | {d['estimate']:.5f} ± {d['se']:.5f} |")
    lines += ["", "## Delay periodicity", "",
              "Each receiver and receiver-mean trace is analyzed separately for each theta. Uniform sweeps with at least eight points use a linearly detrended Hann periodogram. The dominant nonzero frequency, Fourier-bin resolution, cycles in the observed span, selected-frequency sinusoid amplitude and first positive autocorrelation peak are saved. Peaks selected from the same trace are exploratory; no post-selection significance or shared physical cause is established. Fewer than three cycles are flagged as poorly resolved against smooth drift; fewer than four grid samples per cycle are flagged near Nyquist, where aliasing and sampling resolution limit interpretation. Ordered delays also confound elapsed acquisition time with delay, and no repetition-based frequency uncertainty can be recovered.", "",
              "The table reports receiver-mean trace peaks. Native dt is retained whenever no recorded or documented historical dt is available. Microseconds for May18 Kingston use an explicitly marked same-device/day inference from the memory notebook; September Marrakesh uses dt recorded in the result. Frequency resolution is in cycles per displayed time unit.", "",
              "| Run / theta | Dominant period | Frequency resolution | Cycles in span | Trend-residual variance explained by selected sinusoid |", "|---|---:|---:|---:|---:|"]
    for run in summary["runs"]:
        for p in run["periodicity"]:
            if p["trace"] != "receiver_mean":
                continue
            label = f"{run['filename'][4:-5]} / {p['theta_index']}"
            if p["status"] != "exploratory":
                lines.append(f"| {label} | Unavailable: {p['reason']} | — | — | — |")
            else:
                flag = " (few cycles)" if p["few_cycles"] else (" (near Nyquist)" if p["near_nyquist"] else "")
                lines.append(f"| {label} | {p['dominant_period']:.3f} {p['time_unit']} | {p['frequency_resolution']:.6f} | {p['cycles_in_observed_span']:.2f}{flag} | {p['fraction_trend_residual_variance_explained']:.3f} |")
    lines += ["", "## Standalone memory records", "",
              "One duplicate save of job d82dopugbeec73allus0 is excluded. Encoded/bare labels were not saved in legacy JSON; the manifest attributes them from archived notebook definitions, job outputs and comparisons. The two bare controls were collected May18 and June18, unlike the encoded May13 runs; they are not controlled same-session comparisons. Fez remains a separate cohort. Joint receiver-pair quantities are undefined for this single recovered-qubit readout.", "",
              "| File | Backend / opt / encoding | Shots | F(tau=0), 95% Wilson | F(final delay), 95% Wilson |", "|---|---|---:|---|---|"]
    for run in summary["memory_runs"]:
        first, last = run["points"][0]["global_fidelity"], run["points"][-1]["global_fidelity"]
        def interval(item):
            return f"{item['estimate']:.4f} [{item['ci95'][0]:.4f}, {item['ci95'][1]:.4f}]"
        lines.append(f"| {run['filename']} | {run['backend']} / {run['optimization_level']} / {'encoded' if run['use_qec'] else 'bare'} | {run['shots']} | {interval(first)} | {interval(last)} |")
    lines += ["", "## What the saved evidence supports", "",
              "The saved counts establish joint and marginal target-basis success probabilities and often substantial receiver asymmetry. They permit descriptive delay spectra and comparisons of individual records. Mixed backend, date, shot count, optimization, theta and unarchived circuit/layout history prevent a controlled network-size scaling conclusion. September points remain separate from April/May runs even when nominal settings match.", "",
              "New controlled repeated sweeps are needed to estimate reproducible periods and between-job uncertainty. Consistent-backend size points with archived effective configuration, compiled circuit/layout, calibration and shot-aligned outputs are needed for scaling. The old multi-seed convergence image remains withdrawn pending correctly seeded and archived repetitions; this reanalysis collected none.", ""]
    (output_dir / "report.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "analysis" / "hardware")
    args = parser.parse_args()
    analyze(args.output_dir)


if __name__ == "__main__":
    main()
