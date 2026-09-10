#!/usr/bin/env python3
"""Compute statistics and a Markdown report from saved unified hardware records.

Reads results/ by default. Writes JSON and Markdown only; all figures are
created in visualizations.ipynb. No hardware access or new experiment data.
Run with ``python -m broadcasting.analyze_saved_hardware``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "hardware_analysis"

from .analysis import hardware_scaling_points, joint_success_statistics, periodicity_summary
from .provenance import execution_summary
from .results import RESULTS_DIR, list_runs
from .validation import dedupe_by_job, find_duplicate_jobs


def _hardware_records(*results_dirs):
    """Read each logical record once, including distinct cases sharing a job file."""
    by_identity = {}
    for directory in results_dirs or [ROOT / RESULTS_DIR]:
        for run in list_runs(directory):
            if run["experiment_type"] == "hardware":
                identity = (Path(run["filepath"]).resolve(), run["record_id"])
                by_identity.setdefault(identity, run)
    return [by_identity[identity] for identity in sorted(by_identity)]


def load_hardware_runs(*results_dirs):
    """Load broadcasting and memory records, excluding duplicate job/case saves."""
    return dedupe_by_job(_hardware_records(*results_dirs))


def _histogram_points(run):
    """Recompute each theta/delay histogram and verify saved sample totals."""
    counts_grid = run.get("counts")
    theta_samples = run["theta_samples"]
    delays = run["sweep"]["values"]
    if not counts_grid or len(counts_grid) != len(theta_samples):
        raise ValueError(f"Missing or mismatched theta/count grid: {run['filename']}")
    if not delays:
        raise ValueError(f"Empty hardware sweep: {run['filename']}")
    invalid_rates = (run.get("metadata") or {}).get("invalid_sender_rate")
    if invalid_rates is not None and (len(invalid_rates) != len(theta_samples)
                                     or any(len(row) != len(delays) for row in invalid_rates)):
        raise ValueError(f"Sender diagnostic grid mismatch: {run['filename']}")
    sender_counts = (run.get("metadata") or {}).get("sender_counts")
    if sender_counts is not None and (len(sender_counts) != len(theta_samples)
                                     or any(len(row) != len(delays) for row in sender_counts)):
        raise ValueError(f"Sender count grid mismatch: {run['filename']}")
    points = []
    for theta_index, row in enumerate(counts_grid):
        if len(row) != len(delays):
            raise ValueError(f"Sweep/count grid mismatch: {run['filename']}")
        for sweep_index, counts in enumerate(row):
            statistics = joint_success_statistics(counts, run["N"])
            if run.get("shots") is not None and statistics["shots"] != run["shots"]:
                raise ValueError(f"Saved shots disagree with joint counts: {run['filename']}")
            invalid_rate = None if invalid_rates is None else invalid_rates[theta_index][sweep_index]
            if invalid_rate is not None and (not np.isfinite(invalid_rate) or not 0 <= invalid_rate <= 1):
                raise ValueError(f"Invalid sender-outcome rate: {run['filename']}")
            invalid_source = "saved_rate" if invalid_rate is not None else None
            if sender_counts is not None:
                histogram = sender_counts[theta_index][sweep_index]
                width = int(run["N"]).bit_length()
                invalid_count, sender_shots = 0, 0
                for bits, count in histogram.items():
                    clean = bits.replace(" ", "")
                    if (len(clean) != run["M"] * width or set(clean) - {"0", "1"}
                            or not isinstance(count, int) or isinstance(count, bool) or count < 0):
                        raise ValueError(f"Invalid sender histogram: {run['filename']}")
                    sender_shots += count
                    value = int(clean, 2)
                    if any(((value >> (sender * width)) & ((1 << width) - 1)) > run["N"]
                           for sender in range(run["M"])):
                        invalid_count += count
                if sender_shots != statistics["shots"]:
                    raise ValueError(f"Sender and receiver shot totals disagree: {run['filename']}")
                measured_rate = invalid_count / sender_shots
                if invalid_rate is not None and not np.isclose(invalid_rate, measured_rate, atol=1e-12, rtol=0):
                    raise ValueError(f"Saved invalid sender rate disagrees with counts: {run['filename']}")
                invalid_rate, invalid_source = measured_rate, "sender_counts"
            points.append({
                "record_id": run["record_id"],
                "filename": run["filename"],
                "experiment_kind": run["experiment_kind"],
                "job_id": run["job_id"],
                "execution": execution_summary(run),
                "theta_index": theta_index,
                "theta_sample": theta_samples[theta_index],
                "sweep_index": sweep_index,
                "tau_dt": delays[sweep_index],
                "invalid_sender_rate": invalid_rate,
                "invalid_sender_rate_source": invalid_source,
                **statistics,
            })
    fidelities = np.asarray([point["local_fidelities"] for point in points]).reshape(
        len(theta_samples), len(delays), run["N"]
    )
    saved_fidelities = np.asarray(run["fidelities"])
    if (saved_fidelities.shape != fidelities.shape[1:]
            or not np.allclose(fidelities.mean(axis=0), saved_fidelities, atol=1e-10, rtol=0)):
        raise ValueError(f"Saved fidelities disagree with joint counts: {run['filename']}")
    per_theta = run.get("per_theta_fidelities")
    if per_theta is not None and (np.asarray(per_theta).shape != fidelities.shape
                                 or not np.allclose(per_theta, fidelities, atol=1e-10, rtol=0)):
        raise ValueError(f"Saved per-theta fidelities disagree with joint counts: {run['filename']}")
    return points, fidelities


def _run_summary(run):
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
    fields = ("record_id", "filename", "timestamp", "experiment_kind", "job_id", "backend", "optimization_level",
              "shots", "M", "N", "alpha", "use_qec", "theta_samples", "state_prep")
    metadata = run.get("metadata") or {}
    invalid_rates = [point["invalid_sender_rate"] for point in points
                     if point["invalid_sender_rate"] is not None]
    compiled = []
    for template in metadata.get("compiled_templates", []):
        layout = template.get("layout") or {}
        final_layout = layout.get("final_index_layout")
        receiver_map = None
        if (run["experiment_kind"] == "broadcasting" and not run["use_qec"]
                and final_layout is not None):
            first_receiver = run["M"] * int(run["N"]).bit_length()
            receiver_map = final_layout[first_receiver:first_receiver + run["N"]]
        compiled.append({
            "sha256": template.get("sha256"),
            "depth": template.get("depth"),
            "operation_counts": template.get("operation_counts", {}),
            "receiver_physical_qubits": receiver_map,
        })
    endpoints = []
    if len(run["sweep"]["values"]) > 1:
        for theta_index, theta_sample in enumerate(run["theta_samples"]):
            trace = [point for point in points if point["theta_index"] == theta_index]
            endpoints.append({
                "theta_index": theta_index, "theta_sample": theta_sample,
                **{label: {
                    "tau_dt": point["tau_dt"], "mean_local": point["mean_local"],
                    "local_fidelities": point["local_fidelities"],
                    "paired_differences": [{"receivers": pair["receivers"],
                                            **pair["fidelity_difference"]} for pair in point["pairs"]],
                    "invalid_sender_rate": point["invalid_sender_rate"],
                } for label, point in [("first", trace[0]), ("last", trace[-1])]},
            })
    summary = {
        **{field: run.get(field) for field in fields},
        "execution": execution_summary(run),
        "dt_seconds": metadata.get("dt"),
        "initial_layout": metadata.get("initial_layout"),
        "compiled_templates": compiled,
        "trace_endpoints": endpoints,
        "provenance": metadata.get("provenance", {}),
        "filepath": str(Path(run["filepath"]).resolve()),
        "sha256": hashlib.sha256(Path(run["filepath"]).read_bytes()).hexdigest(),
        "record_count": len(points),
        "tau0": [point for point in points if point["tau_dt"] == 0],
        "periodicity": spectra,
        "sender_diagnostics": {
            "recorded_histograms": len(invalid_rates),
            "minimum_invalid_rate": min(invalid_rates) if invalid_rates else None,
            "maximum_invalid_rate": max(invalid_rates) if invalid_rates else None,
        },
    }
    if run["experiment_kind"] == "memory":
        summary["points"] = points
        summary["scope"] = "One recovered-qubit readout; receiver-pair covariance is not defined."
    return points, summary


def analyze(output_dir, *, results_dir=ROOT / RESULTS_DIR, additional_results_dirs=()):
    """Write numeric summaries without pooling jobs, cases, angles, or delays."""
    output_dir, results_dir = Path(output_dir), Path(results_dir).resolve()
    records = _hardware_records(results_dir, *additional_results_dirs)
    if not records:
        raise ValueError(f"No saved hardware records in {results_dir}")
    for run in records:
        if run["sweep"]["axis"] != "tau":
            raise ValueError(f"Expected a tau-axis hardware sweep: {run['filepath']}")
        if run["experiment_kind"] not in {"broadcasting", "memory"}:
            raise ValueError(f"Unknown hardware experiment kind: {run['experiment_kind']}")
    duplicates = {
        kind: find_duplicate_jobs([run for run in records if run["experiment_kind"] == kind])
        for kind in ("broadcasting", "memory")
    }
    hardware = dedupe_by_job(records)
    points, summaries, memory = [], [], []
    for run in hardware:
        run_points, summary = _run_summary(run)
        points.extend(run_points)
        (memory if run["experiment_kind"] == "memory" else summaries).append(summary)
    summary = {
        "method": "Finite-shot statistics per job, case, theta, and delay; no pooling across settings or dates.",
        "limitations": "Wilson and multinomial delta-method intervals assume independent shots with fixed probabilities. Drift, shot autocorrelation, and calibration variation are not quantified by these intervals. Spectral peaks are exploratory.",
        "source_directory": str(results_dir),
        "additional_source_directories": [str(Path(path).resolve()) for path in additional_results_dirs],
        "broadcasting_jobs": len({run["job_id"] for run in summaries}),
        "broadcasting_records": len(summaries),
        "broadcasting_histograms": sum(run["record_count"] for run in summaries),
        "memory_jobs": len({run["job_id"] for run in memory}),
        "memory_records": len(memory),
        "memory_histograms": sum(run["record_count"] for run in memory),
        "duplicate_broadcasting_jobs": duplicates["broadcasting"],
        "duplicate_memory_jobs": duplicates["memory"],
        "runs": summaries,
        "memory_runs": memory,
    }
    scaling_points = hardware_scaling_points(hardware)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in [("points", points), ("summary", summary), ("scaling_points", scaling_points)]:
        (output_dir / f"{name}.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    _write_report(summary, output_dir)
    print(f"Analyzed {summary['broadcasting_jobs']} broadcasting jobs / {len(summaries)} records "
          f"and {summary['memory_jobs']} memory jobs / {len(memory)} records ({len(points)} histograms).")
    print(f"Derived report: {output_dir / 'report.md'}")
    return summary


def _run_label(run, theta_index=None):
    execution = run.get("execution") or {}
    if execution.get("case_id") is not None:
        label = f"repeat {execution.get('repeat_index', '?')} / {execution['case_id']}"
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
        f"**{summary['memory_jobs']} unique standalone memory jobs**. "
        "This analysis collected no data and did not change raw JSON files.", "",
        "Use `python -m broadcasting.analyze_saved_hardware --results-dir RESULTS --output-dir OUTPUT` "
        "to reproduce. `summary.json` records source hashes, configuration, execution case/repeat "
        "identities, tau-zero estimates, and each trace's spectral summary. `points.json` "
        "contains every broadcasting and memory histogram's statistics. See the project README for setup "
        "and the collection workflow; `manuscript/figure_sources.json` pins publication inputs.", "",
    ]
    execution_runs = [run for run in summary["runs"] if run.get("execution")]
    if execution_runs:
        lines += [
            "## Execution identity and inserted delays", "",
            "Case names are labels; the archived factor vector defines the intervention. "
            "For receiver i, `added delay = receiver_delay_factors[i] × tau_dt`, in backend "
            "dt units. A zero factor inserts no extra delay on that receiver. Other gates "
            "and scheduler-induced idle time still contribute. Spectral periods are "
            "reported against the sweep parameter tau, not each receiver's multiplied delay.", "",
            "| Run ID | Repeat (zero-based) | Runtime job ID | Case | Receiver delay factors |",
            "|---|---:|---|---|---|",
        ]
        for run in execution_runs:
            execution = run["execution"]
            lines.append(_table_row(
                execution.get("run_id", "—"), execution.get("repeat_index", "—"), run["job_id"],
                execution.get("case_id", "—"), execution.get("receiver_delay_factors", "unrecorded"),
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
        "Rows remain separate by job/case/theta. `scaling_points.json` contains the opt3, "
        "zero-delay receiver means and ranges with each observation's identity. Receiver "
        "ranges describe heterogeneity, not statistical uncertainty. All optimization levels "
        "remain in the statistics below. Figure rendering is controlled in `visualizations.ipynb`.", "",
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
        "", "## Repeated delay observations", "",
        "Rows retain each run and phase independently. Physical receiver indices follow "
        "the final compiled layout; depth and CZ counts describe the compiled template, "
        "not measured device duration. Endpoint intervals are conditional 95% shot intervals, "
        "unadjusted across runs and endpoints. Differences across phase-changing repetitions "
        "also include execution variation; these observations do not isolate phase dependence "
        "or calibration drift.", "",
        "| Backend / run | Phase (rad) | Physical receivers | Depth / CZ | Mean first → last | F1 − F2 first (95%) | F1 − F2 last (95%) | Invalid sender rate first → last |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for run in summary["runs"]:
        if run["N"] != 2 or run["execution"].get("repeat_index") is None:
            continue
        for trace in run["trace_endpoints"]:
            compiled = run["compiled_templates"]
            template = compiled[trace["theta_index"]] if trace["theta_index"] < len(compiled) else {}
            first, last = trace["first"], trace["last"]
            invalid = [point["invalid_sender_rate"] for point in (first, last)]
            lines.append(_table_row(
                f"{run['backend']} / {_run_label(run, trace['theta_index'])}",
                ", ".join(f"{phase:.5g}" for phase in trace["theta_sample"]),
                template.get("receiver_physical_qubits", "unrecorded"),
                f"{template.get('depth', '—')} / {template.get('operation_counts', {}).get('cz', '—')}",
                f"{first['mean_local']['estimate']:.4f} → {last['mean_local']['estimate']:.4f}",
                _interval_text(first["paired_differences"][0]),
                _interval_text(last["paired_differences"][0]),
                " → ".join("unrecorded" if rate is None else f"{rate:.4f}" for rate in invalid),
            ))
    lines += [
        "", "## Invalid sender outcomes", "",
        "An outcome is invalid when any sender's binary value exceeds N. When N+1 is a "
        "power of two there are no unused binary values, so a zero invalid rate is automatic "
        "and does not imply an error-free circuit. Rates are recomputed from saved sender "
        "histograms when available and checked against saved summaries and receiver shot "
        "totals. Their evidence source is recorded per histogram in `points.json`. "
        "The range below spans recorded settings within a run; it is not an uncertainty "
        "interval. Unrecorded diagnostics remain unknown. No shots are postselected, and "
        "sender--receiver conditional analysis requires the saved aligned readouts.", "",
        "| Run | Histograms with recorded rates | Minimum rate | Maximum rate |",
        "|---|---:|---:|---:|",
    ]
    for run in summary["runs"]:
        diagnostics = run["sender_diagnostics"]
        low, high = diagnostics["minimum_invalid_rate"], diagnostics["maximum_invalid_rate"]
        lines.append(_table_row(
            _run_label(run), diagnostics["recorded_histograms"],
            "unrecorded" if low is None else f"{low:.6f}",
            "unrecorded" if high is None else f"{high:.6f}",
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
        "The table reports receiver-mean peaks. Recorded or evidence-attributed "
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
            "unless recorded or attributed with evidence in the record provenance.", "",
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
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / RESULTS_DIR,
                        help="Directory of measured run records and collected execution JSON files.")
    parser.add_argument("--include-results-dir", type=Path, action="append", default=[],
                        help="Additional saved-data root; repeat to compare separately stored records.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="Derived JSON and Markdown directory; defaults to broadcasting/hardware_analysis.")
    args = parser.parse_args(argv)
    analyze(args.output_dir, results_dir=args.results_dir, additional_results_dirs=args.include_results_dir)


if __name__ == "__main__":
    main()
