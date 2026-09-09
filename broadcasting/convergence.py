"""Restore the original convergence curve and checkpoint compatible repetitions.

Historical points are rounded summaries recovered from the original notebook,
not independent repetitions or reconstructed raw trajectories. New runs retain
full fidelity grids and their exact reference before a plot is made.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import uuid

import matplotlib.pyplot as plt
import numpy as np

from .backend import ExactBackend, SamplingBackend
from .plotting import save_figure
from .protocol import ProtocolConfig
from .results import load_run, save_run, write_run_json

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_PATH = ROOT / "analysis/convergence/historical_summary.json"
METRIC = "sum_over_receivers_trapezoid_over_p_absolute_fidelity_error"
NOISE_MODEL = "independent_physical_depolarizing"


@dataclass
class ConvergenceStudy:
    config: ProtocolConfig
    sample_counts: list[int]
    historical: dict
    repetitions: list[dict]
    archive_dir: Path


def _read(path):
    return json.loads(Path(path).read_text())


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _scenario(config):
    """Seed and trajectory count vary; every physical setting must match."""
    data = asdict(config)
    data.pop("seed")
    data.pop("n_samples")
    return data


def _config_from_run(run):
    if run["sweep"]["axis"] != "p" or len(run["theta_samples"]) != 1:
        raise ValueError("Convergence needs a single-angle depolarizing sweep.")
    return ProtocolConfig(M=run["M"], N=run["N"], alpha=run["alpha"],
                          thetas=run["theta_samples"][0], p_list=run["sweep"]["values"],
                          use_qec=run["use_qec"], outcomes_list=run["outcomes_list"],
                          linear_feedforward=run.get("linear_feedforward", True))


def fidelity_error(sampled, exact, probabilities):
    """Integrated absolute fidelity error per receiver on an identical p grid."""
    sampled, exact, p = np.asarray(sampled), np.asarray(exact), np.asarray(probabilities)
    if (sampled.shape != exact.shape or sampled.ndim != 2 or len(p) != len(exact)
            or len(p) < 2 or not np.all(np.diff(p) > 0)):
        raise ValueError("Fidelity arrays must share one increasing p grid and receiver shape.")
    if not np.all(np.isfinite(sampled)) or not np.all(np.isfinite(exact)):
        raise ValueError("Fidelity arrays must be finite.")
    return np.trapezoid(np.abs(sampled - exact), p, axis=0)


def _reference(batch_dir, config):
    path = batch_dir / "exact.json"
    run = load_run(path)
    if run["backend"] != "aer_exact" or _scenario(_config_from_run(run)) != _scenario(config):
        raise ValueError(f"Exact reference has different physical settings: {path}")
    return run, _digest(path)


def _measurement(path, config, reference, reference_hash):
    run = load_run(path)
    meta = run.get("metadata", {}).get("convergence", {})
    if (_scenario(_config_from_run(run)) != _scenario(config)
            or run["backend"] != "aer_sampling"
            or meta.get("metric") != METRIC
            or meta.get("exact_sha256") != reference_hash):
        raise ValueError(f"Incompatible convergence measurement: {path}")
    errors = fidelity_error(run["fidelities"], reference["fidelities"], config.p_list)
    if not np.allclose(errors, meta.get("errors_per_receiver", []), rtol=1e-12, atol=1e-14):
        raise ValueError(f"Stored convergence errors disagree with raw fidelities: {path}")
    return run, errors


def load_historical_convergence(*, archive_dir=None, historical_path=HISTORICAL_PATH):
    """Read the original curve and compatible checkpointed runs, without computing data.

    Other simulation scenarios are excluded, never interpolated or pooled. A
    corrupt checkpoint belonging to this scenario raises rather than disappearing.
    """
    history = _read(historical_path)
    config = ProtocolConfig(**history["config"])
    archive_dir = Path(archive_dir) if archive_dir else ROOT / "results/convergence"
    repetitions = []
    for manifest_path in sorted(archive_dir.glob("*/study.json")):
        manifest = _read(manifest_path)
        if (manifest.get("metric") != METRIC or manifest.get("noise_model") != NOISE_MODEL
                or _scenario(ProtocolConfig(**manifest["config"])) != _scenario(config)):
            continue
        batch_dir = manifest_path.parent
        if not (batch_dir / "exact.json").exists():
            continue
        reference, reference_hash = _reference(batch_dir, config)
        for seed in manifest["seeds"]:
            points = []
            for count in manifest["sample_counts"]:
                path = batch_dir / f"run_seed{seed}_n{count}.json"
                if not path.exists():
                    continue
                run, errors = _measurement(path, config, reference, reference_hash)
                if run["seed"] != seed or run["n_samples"] != count:
                    raise ValueError(f"Seed/count disagree with checkpoint name: {path}")
                points.append({"n_samples": count, "errors_per_receiver": errors.tolist(), "path": str(path)})
            if points:
                repetitions.append({"seed": seed, "batch": batch_dir.name, "points": points,
                                    "complete": len(points) == len(manifest["sample_counts"])})
    return ConvergenceStudy(config, history["sample_counts"], history, repetitions, archive_dir)


def _positive_integers(values, name, *, allow_zero=False):
    values = list(values)
    minimum = 0 if allow_zero else 1
    if not values or any(isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < minimum for x in values):
        raise ValueError(f"{name} must contain {'nonnegative' if allow_zero else 'positive'} integers.")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must be distinct.")
    return [int(x) for x in values]


def collect_convergence_repeats(study, *, repeats=2, seeds=None, batch_dir=None, sample_counts=None):
    """Run explicit local repetitions, resuming a fixed batch directory safely.

    Each completed trajectory-count sweep is archived immediately. Re-executing
    with the same directory/config skips those points and reuses its saved exact
    reference. A change of parameters requires a new directory. Samples within
    each seed curve are correlated; separate seeds are plotted separately.
    """
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer.")
    counts = _positive_integers(study.sample_counts if sample_counts is None else sample_counts, "sample_counts")
    if counts != sorted(counts):
        raise ValueError("sample_counts must be increasing.")
    batch_dir = Path(batch_dir) if batch_dir else study.archive_dir / f"repeat_{uuid.uuid4().hex[:12]}"
    manifest_path = batch_dir / "study.json"
    previous = _read(manifest_path) if manifest_path.exists() else None
    used = {study.config.seed} | {item["seed"] for item in study.repetitions if item["batch"] != batch_dir.name}
    if seeds is None:
        if previous:
            seeds = previous["seeds"]
        else:
            first = max(seed for seed in used if seed is not None) + 1
            seeds = list(range(first, first + repeats))
    seeds = _positive_integers(seeds, "seeds", allow_zero=True)
    if len(seeds) != repeats or used.intersection(seeds):
        raise ValueError("Choose one new distinct seed per repeat, excluding previously used seeds.")
    manifest = {"schema_version": 1, "config": asdict(study.config), "sample_counts": counts,
                "seeds": seeds, "metric": METRIC, "noise_model": NOISE_MODEL,
                "historical_source": study.historical["source"]}
    if previous is not None and previous != manifest:
        raise ValueError("Batch settings changed; use a new batch_dir or restore the original settings.")
    batch_dir.mkdir(parents=True, exist_ok=True)
    if previous is None:
        write_run_json(manifest, manifest_path)
    exact_path = batch_dir / "exact.json"
    if not exact_path.exists():
        print("Computing the exact reference for this batch…", flush=True)
        exact_config = replace(study.config, n_samples=None)
        exact = ExactBackend().run(exact_config)
        save_run(exact, exact_config, filepath=exact_path)
    reference, reference_hash = _reference(batch_dir, study.config)
    for seed in seeds:
        for count in counts:
            path = batch_dir / f"run_seed{seed}_n{count}.json"
            if path.exists():
                run, _ = _measurement(path, study.config, reference, reference_hash)
                if run["seed"] != seed or run["n_samples"] != count:
                    raise ValueError(f"Seed/count disagree with checkpoint name: {path}")
                print(f"Reusing seed={seed}, trajectories={count:,}", flush=True)
                continue
            config = replace(study.config, seed=seed, n_samples=count)
            print(f"Running seed={seed}, trajectories={count:,} across {len(config.p_list)} p values…", flush=True)
            sampled = SamplingBackend().run(config)
            if sampled.metadata.get("seed") != seed or sampled.metadata.get("n_samples") != count:
                raise ValueError("Sampling backend did not use the requested seed and trajectory count.")
            errors = fidelity_error(sampled.fidelities, reference["fidelities"], config.p_list)
            sampled.metadata["convergence"] = {"metric": METRIC, "exact_sha256": reference_hash,
                                                "errors_per_receiver": errors.tolist(), "batch": batch_dir.name}
            save_run(sampled, config, filepath=path)
            print(f"Saved {path.name}: total error={errors.sum():.6g}", flush=True)
    return batch_dir


def plot_convergence(study, *, output_path=None):
    """Log-log total error, original curve and each new seed kept separate."""
    if output_path is not None and Path(output_path).suffix.lower() != ".png":
        raise ValueError("Convergence figures are PNG only.")
    fig, ax = plt.subplots(figsize=(7, 4.6))
    counts = np.asarray(study.sample_counts)
    historical = np.asarray(study.historical["errors_per_receiver"]).sum(axis=1)
    ax.loglog(counts, historical, "o-", color="black", markersize=4,
              label=f"Historical seed {study.config.seed} (notebook summaries)")
    for repetition in study.repetitions:
        points = repetition["points"]
        x = [point["n_samples"] for point in points]
        y = [sum(point["errors_per_receiver"]) for point in points]
        positive = np.asarray(y) > 0
        suffix = " (partial)" if not repetition["complete"] else ""
        ax.loglog(np.asarray(x)[positive], np.asarray(y)[positive], "o-", markersize=4,
                  label=f"Seed {repetition['seed']}, {repetition['batch']}{suffix}")
        if not np.all(positive):
            ax.text(0.02, 0.02, "Zero-error points omitted on logarithmic y axis.", transform=ax.transAxes, fontsize=8)
    reference = historical[0] * np.sqrt(counts[0] / counts)
    ax.loglog(counts, reference, ":", color="0.5", label=r"$n^{-1/2}$ reference (anchored to first historical point)")
    ax.set(xlabel="Monte Carlo trajectories per noise probability", ylabel="Integrated absolute fidelity error (sum over receivers)")
    ax.grid(which="both", alpha=0.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    if output_path is not None:
        save_figure(fig, output_path)
    return fig
