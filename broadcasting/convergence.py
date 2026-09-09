"""Numerical convergence studies using the shared experiment-record format.

Each study indexes immutable exact and sampled measurements. Seed 0 has only
rounded error summaries; it remains explicitly separate from raw fidelity grids.
All plotting belongs to visualizations.ipynb.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np

from .backend import ExactBackend, SamplingBackend
from .protocol import ProtocolConfig
from .results import RESULTS_DIR, load_run, save_run, write_run_json

ROOT = Path(__file__).resolve().parent.parent
SEED_ZERO_PATH = ROOT / "results/convergence/seed_zero.json"
METRIC = "sum_over_receivers_trapezoid_over_p_absolute_fidelity_error"
NOISE_MODEL = "independent_physical_depolarizing"


@dataclass
class ConvergenceStudy:
    config: ProtocolConfig
    sample_counts: list[int]
    seed_zero: dict
    repetitions: list[dict]
    archive_dir: Path


def _resolve_record(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def _stored_path(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _measurement_path(batch_dir, seed, count):
    manifest = _read(Path(batch_dir) / "study.json")
    return _resolve_record(manifest["measurement_paths"][f"seed{seed}_n{count}"])


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
    if (p.ndim != 1 or not np.all(np.isfinite(p))
            or sampled.shape != exact.shape or sampled.ndim != 2 or len(p) != len(exact)
            or len(p) < 2 or not np.all(np.diff(p) > 0)):
        raise ValueError("Fidelity arrays must share one increasing p grid and receiver shape.")
    if not np.all(np.isfinite(sampled)) or not np.all(np.isfinite(exact)):
        raise ValueError("Fidelity arrays must be finite.")
    return np.trapezoid(np.abs(sampled - exact), p, axis=0)


def _reference(batch_dir, config):
    path = _resolve_record(_read(Path(batch_dir) / "study.json")["exact_path"])
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


def load_convergence(*, archive_dir=None, seed_zero_path=SEED_ZERO_PATH):
    """Load compatible saved studies, preserving every seed and native sample grid."""
    seed_zero = _read(seed_zero_path)
    config = ProtocolConfig(**seed_zero["config"])
    archive_dir = Path(archive_dir) if archive_dir else ROOT / "results/convergence"
    repetitions = []
    for manifest_path in sorted(archive_dir.glob("*/study.json")):
        manifest = _read(manifest_path)
        if (manifest.get("metric") != METRIC or manifest.get("noise_model") != NOISE_MODEL
                or _scenario(ProtocolConfig(**manifest["config"])) != _scenario(config)):
            continue
        batch_dir = manifest_path.parent
        if not _resolve_record(manifest["exact_path"]).exists():
            continue
        reference, reference_hash = _reference(batch_dir, config)
        for seed in manifest["seeds"]:
            points = []
            for count in manifest["sample_counts"]:
                path = _measurement_path(batch_dir, seed, count)
                if not path.exists():
                    continue
                run, errors = _measurement(path, config, reference, reference_hash)
                if run["seed"] != seed or run["n_samples"] != count:
                    raise ValueError(f"Seed/count disagree with study index: {path}")
                points.append({"n_samples": count, "errors_per_receiver": errors.tolist(), "path": str(path)})
            if points:
                repetitions.append({"seed": seed, "batch": batch_dir.name, "points": points,
                                    "complete": len(points) == len(manifest["sample_counts"]),
                                    "exact_path": str(_resolve_record(manifest["exact_path"])),
                                    "study_path": str(manifest_path)})
    return ConvergenceStudy(config, seed_zero["sample_counts"], seed_zero, repetitions, archive_dir)


def _positive_integers(values, name, *, allow_zero=False):
    values = list(values)
    minimum = 0 if allow_zero else 1
    if not values or any(isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < minimum for x in values):
        raise ValueError(f"{name} must contain {'nonnegative' if allow_zero else 'positive'} integers.")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must be distinct.")
    return [int(x) for x in values]


def collect_convergence_repeats(study, *, repeats=2, seeds=None, batch_dir=None,
                                sample_counts=None, results_dir=RESULTS_DIR):
    """Collect explicitly requested local runs, resuming without rewriting results.

    The study contains only an index and numerical settings. Exact and sampled
    grids use the same shared record store as every other experiment.
    """
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer.")
    counts = _positive_integers(study.sample_counts if sample_counts is None else sample_counts, "sample_counts")
    if counts != sorted(counts):
        raise ValueError("sample_counts must be increasing.")
    batch_dir = Path(batch_dir) if batch_dir else study.archive_dir / f"study_{uuid.uuid4().hex[:12]}"
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
    settings = {"config": asdict(study.config), "sample_counts": counts,
                "seeds": seeds, "metric": METRIC, "noise_model": NOISE_MODEL}
    if previous is not None:
        if any(previous.get(key) != value for key, value in settings.items()):
            raise ValueError("Study settings changed; use a new batch_dir or restore the original settings.")
        manifest = previous
    else:
        study_id = uuid.uuid4().hex
        directory = Path(results_dir).resolve()
        manifest = {"schema_version": 2, "study_id": study_id, **settings,
                    "exact_path": _stored_path(directory / f"run_{study_id}_exact.json"),
                    "measurement_paths": {
                        f"seed{seed}_n{count}": _stored_path(directory / f"run_{study_id}_seed{seed}_n{count}.json")
                        for seed in seeds for count in counts}}
        batch_dir.mkdir(parents=True, exist_ok=True)
        write_run_json(manifest, manifest_path)
    exact_path = _resolve_record(manifest["exact_path"])
    if not exact_path.exists():
        print("Computing the exact reference…", flush=True)
        exact_config = replace(study.config, n_samples=None)
        exact = ExactBackend().run(exact_config)
        save_run(exact, exact_config, filepath=exact_path)
    reference, reference_hash = _reference(batch_dir, study.config)
    for seed in seeds:
        for count in counts:
            path = _resolve_record(manifest["measurement_paths"][f"seed{seed}_n{count}"])
            if path.exists():
                run, _ = _measurement(path, study.config, reference, reference_hash)
                if run["seed"] != seed or run["n_samples"] != count:
                    raise ValueError(f"Seed/count disagree with study index: {path}")
                print(f"Reusing seed={seed}, trajectories={count:,}", flush=True)
                continue
            config = replace(study.config, seed=seed, n_samples=count)
            print(f"Running seed={seed}, trajectories={count:,} across {len(config.p_list)} probabilities…", flush=True)
            sampled = SamplingBackend().run(config)
            if sampled.metadata.get("seed") != seed or sampled.metadata.get("n_samples") != count:
                raise ValueError("Sampling backend did not use the requested seed and trajectory count.")
            errors = fidelity_error(sampled.fidelities, reference["fidelities"], config.p_list)
            sampled.metadata["convergence"] = {"metric": METRIC, "exact_sha256": reference_hash,
                                                "errors_per_receiver": errors.tolist(), "batch": batch_dir.name}
            save_run(sampled, config, filepath=path)
            print(f"Saved {path.name}: total error={errors.sum():.6g}", flush=True)
    return batch_dir
