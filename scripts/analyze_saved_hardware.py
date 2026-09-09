#!/usr/bin/env python3
"""Reanalyze existing receiver counts; no hardware access or new experiment data.

Writes per-job/case/theta/delay statistics and a report under analysis/hardware/
by default. Use --results-dir RUN_DIR/results for collected hardware campaigns.
Historical source overlays are explicit in figures/sources.json and never change
raw results or the publication manifest.
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
from broadcasting.plotting import plot_delay_repeats, plot_hardware_scaling, save_figure
from broadcasting.results import load_run, run_paths
from broadcasting.validation import dedupe_by_job, find_duplicate_jobs
from scripts.figure_sources import load_source, source_manifest


def _relative_source(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else None


def _source_run(path, manifest):
    """Apply documented historical fields only to pinned files in this checkout."""
    relative = _relative_source(path)
    if relative in manifest["runs"]:
        return load_source(relative, manifest=manifest)
    return load_run(path)


def load_hardware_runs(*results_dirs):
    """Load historical and campaign hardware with source overlays, read-only.

    Search supplied directories recursively for run/repeat experiment records.
    Repeated paths and duplicate job/case saves are included only once. The
    default root includes historical records and any campaigns saved beneath it.
    """
    manifest = source_manifest()
    paths = sorted({path.resolve() for directory in (results_dirs or [ROOT / "results"])
                    for path in run_paths(directory)})
    runs = [_source_run(path, manifest) for path in paths]
    return dedupe_by_job([run for run in runs if run["experiment_type"] == "hardware"])


def _histogram_points(run):
    """Validate the saved grid, recompute its statistics, and check fidelities."""
    counts_grid = run.get("counts")
    theta_samples = run["theta_samples"]
    delays = run["sweep"]["values"]
    if not counts_grid or len(counts_grid) != len(theta_samples):
        raise ValueError(f"Missing or mismatched theta/count grid: {run['filename']}")
    points = []
    for theta_index, row in enumerate(counts_grid):
        if len(row) != len(delays):
            raise ValueError(f"Sweep/count grid mismatch: {run['filename']}")
        for sweep_index, counts in enumerate(row):
            statistics = joint_success_statistics(counts, run["N"])
            if run.get("shots") is not None and statistics["shots"] != run["shots"]:
                raise ValueError(f"Saved shots disagree with joint counts: {run['filename']}")
            points.append({
                "filename": run["filename"],
                "job_id": run["job_id"],
                "campaign": (run.get("metadata") or {}).get("campaign", {}),
                "theta_index": theta_index,
                "sweep_index": sweep_index,
                "tau_dt": delays[sweep_index],
                **statistics,
            })
    fidelities = np.asarray([point["local_fidelities"] for point in points]).reshape(
        len(theta_samples), len(delays), run["N"]
    )
    if not np.allclose(fidelities.mean(axis=0), run["fidelities"], atol=1e-10, rtol=0):
        raise ValueError(f"Saved fidelities disagree with joint counts: {run['filename']}")
    return points, fidelities


def _broadcasting_summary(run, manifest):
    points, fidelities = _histogram_points(run)
    spectra = []
    for theta_index, theta_fidelities in enumerate(fidelities):
        trace_run = dict(run, fidelities=theta_fidelities.tolist())
        for receiver in [None, *range(run["N"])]:
            spectra.append({
                "theta_index": theta_index,
                "trace": "receiver_mean" if receiver is None else f"receiver_{receiver}",
                **periodicity_summary(trace_run, receiver=receiver),
            })
    source = manifest["runs"].get(_relative_source(run["filepath"]), {})
    fields = ("filename", "timestamp", "job_id", "backend", "optimization_level",
              "shots", "M", "N", "alpha", "use_qec", "theta_samples")
    summary = {
        **{field: run.get(field) for field in fields},
        "campaign": (run.get("metadata") or {}).get("campaign", {}),
        "sha256": hashlib.sha256(Path(run["filepath"]).read_bytes()).hexdigest(),
        "historical_provenance": run.get("historical_provenance", {}),
        "circuit_history": source.get("circuit_history", "See saved execution metadata when available."),
        "record_count": len(points),
        "tau0": [point for point in points if point["tau_dt"] == 0],
        "periodicity": spectra,
    }
    return points, summary


def _memory_summaries(results_dir, manifest):
    """Standalone memory records have one receiver and a separate saved schema."""
    summaries, duplicates, seen_jobs = [], {}, {}
    for path in sorted((results_dir / "qec513").glob("*.json")):
        relative = _relative_source(path)
        run = load_source(relative, manifest=manifest) if relative in manifest["runs"] else json.loads(path.read_text())
        job = run["job_id"]
        if job in seen_jobs:
            duplicates.setdefault(job, [seen_jobs[job]]).append(path.name)
            continue
        seen_jobs[job] = path.name
        stats = [joint_success_statistics(counts, 1) for counts in run["backend_counts"]]
        fidelities = [point["global_fidelity"]["estimate"] for point in stats]
        if not np.allclose(fidelities, run["backend_fidelities"], atol=1e-10, rtol=0):
            raise ValueError(f"Saved QEC fidelity disagrees with counts: {path.name}")
        trace = {
            "N": 1,
            "sweep": {"axis": "tau", "values": run["tau_values"]},
            "fidelities": [[value] for value in fidelities],
            "metadata": run.get("metadata", {}),
        }
        fields = ("backend", "optimization_level", "shots", "state_prep", "use_qec")
        summaries.append({
            "filename": path.name,
            "job_id": job,
            **{field: run.get(field) for field in fields},
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "historical_provenance": run.get("historical_provenance", {}),
            "points": [{"tau_dt": tau, **point} for tau, point in zip(run["tau_values"], stats)],
            "periodicity": periodicity_summary(trace),
            "scope": "One recovered-qubit readout; receiver-pair covariance is not defined.",
        })
    return summaries, duplicates


def analyze(output_dir, *, results_dir=ROOT / "results", additional_results_dirs=()):
    """Analyze saved directories, retaining separate job/case/theta records."""
    output_dir, results_dir = Path(output_dir), Path(results_dir).resolve()
    manifest = source_manifest()
    hardware = []
    paths = sorted({path.resolve() for directory in [results_dir, *additional_results_dirs]
                    for path in run_paths(directory)})
    for path in paths:
        run = _source_run(path, manifest)
        if run["experiment_type"] == "hardware":
            if run["sweep"]["axis"] != "tau":
                raise ValueError(f"Expected a tau-axis hardware sweep: {path}")
            hardware.append(run)
    if not hardware:
        raise ValueError(f"No saved hardware records in {results_dir}")
    duplicates = find_duplicate_jobs(hardware)
    hardware = dedupe_by_job(hardware)
    points, summaries = [], []
    for run in hardware:
        run_points, summary = _broadcasting_summary(run, manifest)
        points.extend(run_points)
        summaries.append(summary)
    memory, memory_duplicates = _memory_summaries(results_dir, manifest)
    summary = {
        "method": "Finite-shot statistics per job, case, theta, and delay; no pooling across settings or dates.",
        "limitations": "Wilson and multinomial delta-method intervals assume independent shots with fixed probabilities. Drift, shot autocorrelation, and calibration variation are not quantified by these intervals. Spectral peaks are exploratory.",
        "source_directory": str(results_dir),
        "additional_source_directories": [str(Path(path).resolve()) for path in additional_results_dirs],
        "historical_sources": results_dir == ROOT / "results",
        "broadcasting_jobs": len({run["job_id"] for run in hardware}),
        "broadcasting_records": len(hardware),
        "broadcasting_histograms": len(points),
        "qec_unique_jobs": len(memory),
        "duplicate_broadcasting_jobs": duplicates,
        "duplicate_qec_jobs": memory_duplicates,
        "runs": summaries,
        "memory_runs": memory,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in [("points", points), ("summary", summary)]:
        (output_dir / f"{name}.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    if any(run["tau0"] and run["optimization_level"] == 3 for run in summaries):
        fig = plot_hardware_scaling(hardware)
        save_figure(fig, output_dir / "tau0_fidelities.png")
        (output_dir / "scaling_points.json").write_text(
            json.dumps(fig.broadcasting_points, indent=2, allow_nan=False) + "\n")
        plt.close(fig)
    if any(run["tau0"] for run in summaries):
        _derived_joint_figure(summaries, output_dir)
    # One file per job/case keeps large repeat campaigns readable and preserves
    # the individual random-angle traces instead of averaging them together.
    for run in hardware:
        if len(run["sweep"]["values"]) > 1:
            fig = plot_delay_repeats([run])
            save_figure(fig, output_dir / "delay_sweeps" / f"{Path(run['filename']).stem}.png")
            plt.close(fig)
    _write_report(summary, output_dir)
    print(f"Analyzed {summary['broadcasting_jobs']} broadcasting jobs / {len(hardware)} case records "
          f"({len(points)} histograms), {len(memory)} unique memory jobs.")
    print(f"Derived report: {output_dir / 'report.md'}")
    return summary


def _derived_joint_figure(runs, output_dir):
    point_count = sum(len(run["tau0"]) for run in runs)
    fig, ax = plt.subplots(figsize=(8.0, max(5.5, 0.28 * point_count)))
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
            labels.append(_run_label(run, point["theta_index"]))
            y += 1
    ax.set_yticks(range(y), labels, fontsize=7)
    ax.invert_yaxis()
    ax.set(xlim=(0, 1.02), xlabel="Fidelity at τ=0, per job and theta sample")
    ax.grid(axis="x", alpha=0.2)
    ax.legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    save_figure(fig, output_dir / "joint_and_worst_tau0.png")
    plt.close(fig)


def _run_label(run, theta_index=None):
    campaign = run.get("campaign") or {}
    if campaign:
        label = f"repeat {campaign['repeat_index']} / {campaign['case_id']}"
    else:
        label = Path(run["filename"]).stem.removeprefix("run_")
    return label if theta_index is None else f"{label} / θ{theta_index}"


def _interval_text(item, key="ci95"):
    low, high = item[key]
    return f"{item['estimate']:.4f} [{low:.4f}, {high:.4f}]"


def _table_row(*cells):
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _write_report(summary, output_dir):
    lines = [
        "# Saved hardware readout analysis", "",
        f"Derived from **{summary['broadcasting_jobs']} broadcasting jobs / "
        f"{summary['broadcasting_records']} case records / "
        f"{summary['broadcasting_histograms']} per-theta, per-delay histograms** and "
        f"**{summary['qec_unique_jobs']} unique standalone memory jobs**. "
        "This analysis collected no data and did not change raw JSON files.", "",
        "Use `scripts/analyze_saved_hardware.py --results-dir RESULTS --output-dir OUTPUT` "
        "to reproduce. `summary.json` records source hashes, configuration, campaign case/repeat "
        "identities, tau-zero estimates, and each trace's spectral summary. `points.json` "
        "contains every broadcasting histogram's statistics. See the project README for setup "
        "and the collection workflow; `figures/sources.json` pins publication inputs.", "",
    ]
    campaign_runs = [run for run in summary["runs"] if run.get("campaign")]
    if campaign_runs:
        lines += [
            "## Campaign identity and inserted delays", "",
            "Case names are labels; the archived factor vector defines the intervention. "
            "For receiver i, `added delay = receiver_delay_factors[i] × tau_dt`, in backend "
            "dt units. A zero factor inserts no extra delay on that receiver. Other gates "
            "and scheduler-induced idle time still contribute. Spectral periods are "
            "reported against the sweep parameter tau, not each receiver's multiplied delay.", "",
            "| Campaign run ID | Repeat (zero-based) | Runtime job ID | Case | Receiver delay factors |",
            "|---|---:|---|---|---|",
        ]
        for run in campaign_runs:
            campaign = run["campaign"]
            lines.append(_table_row(
                campaign["run_id"], campaign["repeat_index"], run["job_id"],
                campaign["case_id"], campaign["receiver_delay_factors"],
            ))
        lines.append("")
    lines += [
        "## Definitions and uncertainty", "",
        "Receiver success is the zero bit in the target-basis readout, using little-endian "
        "receiver ordering. Joint fidelity is the all-zero frequency; worst fidelity is the "
        "minimum receiver marginal. The product of marginals is reported separately and is "
        "not assumed equal to joint success. Mean-fidelity uncertainty includes shot-level "
        "receiver covariances.", "",
        "Marginal and joint intervals are two-sided 95% Wilson intervals. The worst-receiver "
        "interval uses minimum bounds from Bonferroni-adjusted Wilson intervals, approximately "
        "accounting for receiver selection. Covariance and paired differences use asymptotic "
        "multinomial delta-method intervals, unadjusted for comparisons over delays/pairs; "
        "these may degenerate at boundary counts. Covariance means E[Xi Xj] − E[Xi]E[Xj].", "",
        "These intervals assume independent shots with fixed probabilities within each "
        "histogram. They exclude calibration drift, temporal shot correlation, and job-to-job "
        "variation. Cases sharing a Runtime job remain distinct cases, not independent job "
        "repetitions. Counts are never pooled across jobs, cases, theta samples, or delays. "
        "Canonical delay order in a saved array does not imply execution order; consult the "
        "saved submitted PUB order, shot alignment, and execution-span metadata when available.", "",
        "Nonzero success covariance does not identify correlated physical noise: shared "
        "preparation, feedforward, readout, and drift can contribute. Zero covariance in this "
        "basis also does not rule out correlated noise.", "",
        "## Tau-zero broadcasting results", "",
        "Rows remain separate by job/case/theta. `tau0_fidelities.png` uses opt3 only: "
        "x is the number of receivers, y is fidelity, and color is the number of senders. "
        "Each point is a receiver mean and its vertical bar spans the receiver minimum/maximum. "
        "Small horizontal offsets separate observations; `scaling_points.json` records every plotted identity. "
        "These receiver ranges describe heterogeneity, not statistical uncertainty. "
        "`joint_and_worst_tau0.png` retains all optimization levels with finite-shot intervals. "
        "The `delay_sweeps/` PNGs show each job/case/theta separately with receiver Wilson 95% intervals "
        "and recorded time units.", "",
        "| Run or repeat/case / theta | Backend / opt / shots | M,N | Mean | Worst (95%) | Joint (95%) | Receiver range |",
        "|---|---|---|---:|---|---|---:|",
    ]
    for run in summary["runs"]:
        for point in run["tau0"]:
            settings = f"{run['backend']} / {run['optimization_level']} / {point['shots']}"
            lines.append(_table_row(
                _run_label(run, point["theta_index"]), settings, f"{run['M']},{run['N']}",
                f"{point['mean_local']['estimate']:.4f}",
                _interval_text(point["worst_receiver"], "simultaneous_ci95"),
                _interval_text(point["global_fidelity"]), f"{point['receiver_spread']:.4f}",
            ))
    lines += [
        "", "## Pair covariance and receiver asymmetry", "",
        "Every two-receiver tau-zero pair is shown as estimate ± asymptotic SE. All other "
        "pairs and delays are in `points.json`. No multiplicity-adjusted significance claim "
        "is made.", "",
        "| Run or repeat/case / theta | Cov(success 0, success 1) | F0 − F1 |", "|---|---:|---:|",
    ]
    for run in summary["runs"]:
        if run["N"] != 2:
            continue
        for point in run["tau0"]:
            pair = point["pairs"][0]
            covariance, difference = pair["covariance"], pair["fidelity_difference"]
            lines.append(_table_row(
                _run_label(run, point["theta_index"]),
                f"{covariance['estimate']:.5f} ± {covariance['se']:.5f}",
                f"{difference['estimate']:.5f} ± {difference['se']:.5f}",
            ))
    lines += [
        "", "## Delay periodicity", "",
        "Each receiver and receiver-mean trace is analyzed separately for each job/case/theta. "
        "Uniform sweeps with at least eight points use a linearly detrended Hann periodogram. "
        "Saved summaries include the dominant nonzero frequency, Fourier-bin resolution, "
        "cycles observed, selected-frequency sinusoid amplitude, and first positive "
        "autocorrelation peak. A peak selected from the same trace is exploratory, with no "
        "post-selection significance or physical-cause inference. Fewer than three observed "
        "cycles are poorly resolved against drift; fewer than four samples per cycle are "
        "near Nyquist and limited by sampling/aliasing. Independent repetitions are needed "
        "for frequency uncertainty.", "",
        "The table reports receiver-mean peaks. Recorded or explicitly documented historical "
        "dt converts time to microseconds; otherwise native dt is retained. Frequency "
        "resolution is in cycles per displayed unit.", "",
        "| Run or repeat/case / theta | Dominant period | Frequency resolution | Cycles in span | Trend-residual variance explained |",
        "|---|---:|---:|---:|---:|",
    ]
    for run in summary["runs"]:
        for spectrum in run["periodicity"]:
            if spectrum["trace"] != "receiver_mean":
                continue
            label = _run_label(run, spectrum["theta_index"])
            if spectrum["status"] != "exploratory":
                lines.append(_table_row(label, f"Unavailable: {spectrum['reason']}", "—", "—", "—"))
                continue
            flags = [name for key, name in [("few_cycles", "few cycles"), ("near_nyquist", "near Nyquist")]
                     if spectrum[key]]
            cycles = f"{spectrum['cycles_in_observed_span']:.2f}"
            if flags:
                cycles += f" ({', '.join(flags)})"
            lines.append(_table_row(
                label, f"{spectrum['dominant_period']:.3f} {spectrum['time_unit']}",
                f"{spectrum['frequency_resolution']:.6f}", cycles,
                f"{spectrum['fraction_trend_residual_variance_explained']:.3f}",
            ))
    if summary["memory_runs"]:
        lines += [
            "", "## Standalone memory records", "",
            "Duplicate job saves are excluded. One recovered-qubit readout is available, "
            "so receiver-pair quantities are undefined. Encoding is reported as unknown "
            "unless recorded or attributed with evidence in the source manifest.", "",
            "| File | Backend / opt / encoding | Shots | F(first delay), 95% Wilson | F(final delay), 95% Wilson |",
            "|---|---|---:|---|---|",
        ]
        for run in summary["memory_runs"]:
            qec = run.get("use_qec")
            encoding = "unknown" if qec is None else ("encoded" if qec else "bare")
            settings = f"{run['backend']} / {run['optimization_level']} / {encoding}"
            lines.append(_table_row(
                run["filename"], settings, run["shots"],
                _interval_text(run["points"][0]["global_fidelity"]),
                _interval_text(run["points"][-1]["global_fidelity"]),
            ))
    if summary["historical_sources"]:
        lines += [
            "", "## Historical interpretation", "",
            "The historical histograms do not archive calibrated layouts, circuit revisions, "
            "or shot order. May18 Kingston microseconds use an explicitly marked same-device/day "
            "inference from the memory notebook; September Marrakesh records dt directly. "
            "Optimization, backend, date, theta, and shot counts vary, so these records do not "
            "establish controlled network-size scaling or reproducible delay periods.", "",
            "The duplicate memory save for job d82dopugbeec73allus0 is excluded. Encoded May13 "
            "and bare May18/June18 records were collected on different dates, so they do not "
            "provide a controlled same-session advantage comparison. Fez remains a separate "
            "cohort. These historical hardware records are retained alongside future opt3 repeats; "
            "the README records the remaining data requirements.",
        ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results",
                        help="Root searched recursively for run/repeat experiment JSON files.")
    parser.add_argument("--include-results-dir", type=Path, action="append", default=[],
                        help="Additional saved-data root; repeat to compare historical and campaign results.")
    parser.add_argument("--output-dir", type=Path,
                        help="Derived output directory; defaults to analysis/hardware or beside campaign results.")
    args = parser.parse_args()
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = (ROOT / "analysis/hardware" if args.results_dir.resolve() == ROOT / "results"
                      else args.results_dir.resolve().parent / "analysis")
    analyze(output_dir, results_dir=args.results_dir, additional_results_dirs=args.include_results_dir)


if __name__ == "__main__":
    main()
