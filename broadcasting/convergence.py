"""Numerical convergence from independent, self-contained result JSON files.

Every sampled measurement embeds its study settings and exact reference. The
seed-zero summary retains printed errors and explicitly lacks raw fidelity grids.
All plotting belongs to visualizations.ipynb.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import uuid

import numpy as np

from .backend import ExactBackend, SamplingBackend
from .protocol import ProtocolConfig
from .results import (RESULTS_DIR, list_runs, load_run, make_run_record,
                      validate_run_record, write_run_json)

ROOT = Path(__file__).resolve().parent.parent
SEED_ZERO_PATH = ROOT / "results/run_seed_zero.json"
METRIC = "sum_over_receivers_trapezoid_over_p_absolute_fidelity_error"
NOISE_MODEL = "independent_physical_depolarizing"


@dataclass
class ConvergenceStudy:
    config: ProtocolConfig
    sample_counts: list[int]
    seed_zero: dict
    repetitions: list[dict]
    results_dir: Path


def reference_digest(record):
    """Hash the embedded JSON value independently of file whitespace or location."""
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _scenario(config):
    data = asdict(config)
    data.pop("seed")
    data.pop("n_samples")
    return data


def _config_from_run(run):
    protocol = run["protocol"]
    if run["sweep"]["axis"] != "p" or len(protocol["theta_samples"]) != 1:
        raise ValueError("Convergence needs a single-angle depolarizing sweep.")
    return ProtocolConfig(M=protocol["M"], N=protocol["N"], alpha=protocol["alpha"],
                          thetas=protocol["theta_samples"][0], p_list=run["sweep"]["values"],
                          use_qec=protocol["use_qec"], outcomes_list=protocol["outcomes_list"],
                          linear_feedforward=protocol.get("linear_feedforward", True))


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


def _validate_reference(reference, config):
    if not isinstance(reference, dict) or not isinstance(reference.get("record"), dict):
        raise ValueError("Convergence measurement requires an embedded exact reference")
    record = reference["record"]
    validate_run_record(record)
    if (reference_digest(record) != reference.get("sha256")
            or record.get("backend") != "aer_exact"
            or _scenario(_config_from_run(record)) != _scenario(config)):
        raise ValueError("Incompatible convergence exact reference or checksum")
    return record


def _measurement(run, config):
    meta = run.get("metadata", {}).get("convergence", {})
    reference = _validate_reference(meta.get("exact_reference", {}), config)
    if (_scenario(_config_from_run(run)) != _scenario(config)
            or run["backend"] != "aer_sampling" or meta.get("metric") != METRIC):
        raise ValueError(f"Incompatible convergence measurement: {run.get('record_id')}")
    errors = fidelity_error(run["fidelities"], reference["fidelities"], config.p_list)
    stored = np.asarray(meta.get("errors_per_receiver", []))
    if stored.shape != errors.shape or not np.allclose(errors, stored, rtol=1e-12, atol=1e-14):
        raise ValueError("Stored convergence errors disagree with raw fidelities")
    return errors


def _study_records(results_dir):
    return [run for run in list_runs(results_dir, experiment_kind="broadcasting", experiment_type="simulation")
            if isinstance(run.get("metadata", {}).get("convergence", {}).get("study"), dict)]


def load_convergence(*, results_dir=RESULTS_DIR, seed_zero_path=None):
    """Discover saved repetitions from their embedded settings and reference grids."""
    seed_zero_path = Path(seed_zero_path) if seed_zero_path is not None else Path(results_dir) / "run_seed_zero.json"
    if not seed_zero_path.is_file():
        raise FileNotFoundError("No local convergence summary; supply seed_zero_path explicitly for the study settings")
    seed_zero = load_run(seed_zero_path)
    if seed_zero["experiment_kind"] != "convergence_summary":
        raise ValueError("seed_zero_path must contain an explicit convergence summary")
    config = ProtocolConfig(**seed_zero["config"])
    groups, settings_by_id, reference_by_id = {}, {}, {}
    for run in _study_records(results_dir):
        meta = run["metadata"]["convergence"]
        settings = meta["study"]
        if (settings.get("metric") != METRIC or settings.get("noise_model") != NOISE_MODEL
                or _scenario(ProtocolConfig(**settings["config"])) != _scenario(config)):
            continue
        identity = settings["study_id"]
        if identity in settings_by_id and settings_by_id[identity] != settings:
            raise ValueError(f"Conflicting convergence settings for study {identity}")
        settings_by_id[identity] = settings
        if meta.get("role") == "exact":
            if run["backend"] != "aer_exact" or _scenario(_config_from_run(run)) != _scenario(config):
                raise ValueError(f"Incompatible convergence exact measurement: {identity}")
            continue
        errors = _measurement(run, config)
        checksum = meta["exact_reference"]["sha256"]
        if identity in reference_by_id and reference_by_id[identity] != checksum:
            raise ValueError(f"Conflicting convergence exact references for study {identity}")
        reference_by_id[identity] = checksum
        seed, count = run["seed"], run["n_samples"]
        if seed not in settings["seeds"] or count not in settings["sample_counts"]:
            raise ValueError("Seed/count disagree with embedded study settings")
        points = groups.setdefault((identity, seed), {})
        if count in points:
            raise ValueError(f"Duplicate convergence measurement for study {identity}, seed {seed}, n={count}")
        points[count] = {"n_samples": count, "errors_per_receiver": errors.tolist(),
                         "path": run["filepath"], "record_id": run["record_id"]}
    repetitions = []
    for (identity, seed), points in sorted(groups.items()):
        counts = settings_by_id[identity]["sample_counts"]
        repetitions.append({"study_id": identity, "seed": seed,
                            "points": [points[count] for count in counts if count in points],
                            "complete": len(points) == len(counts)})
    return ConvergenceStudy(config, seed_zero["sample_counts"], seed_zero,
                            repetitions, Path(results_dir))


def _positive_integers(values, name, *, allow_zero=False):
    values = list(values)
    minimum = 0 if allow_zero else 1
    if not values or any(isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < minimum for x in values):
        raise ValueError(f"{name} must contain {'nonnegative' if allow_zero else 'positive'} integers.")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must be distinct.")
    return [int(x) for x in values]


def collect_convergence_repeats(study, *, repeats=2, seeds=None, sample_counts=None,
                                results_dir=RESULTS_DIR, study_id=None):
    """Collect local trajectories into flat JSON files; resume using the same study_id.

    Each completed point remains independently readable after an interruption or
    relocation. Existing files are validated and never overwritten.
    """
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer.")
    counts = _positive_integers(study.sample_counts if sample_counts is None else sample_counts, "sample_counts")
    if counts != sorted(counts):
        raise ValueError("sample_counts must be increasing.")
    study_id = study_id or uuid.uuid4().hex
    if not isinstance(study_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", study_id):
        raise ValueError("study_id must contain only letters, numbers, underscores or hyphens")
    directory = Path(results_dir)
    records = _study_records(directory)
    matching = [run for run in records if run["metadata"]["convergence"]["study"]["study_id"] == study_id]
    previous = matching[0]["metadata"]["convergence"]["study"] if matching else None
    used = {study.config.seed} | {run["seed"] for run in records
                                 if run["metadata"]["convergence"]["study"]["study_id"] != study_id
                                 and run["backend"] == "aer_sampling"
                                 and _scenario(_config_from_run(run)) == _scenario(study.config)}
    if seeds is None:
        if previous:
            seeds = previous["seeds"]
        else:
            first = max((seed for seed in used if seed is not None), default=0) + 1
            seeds = list(range(first, first + repeats))
    seeds = _positive_integers(seeds, "seeds", allow_zero=True)
    if len(seeds) != repeats or used.intersection(seeds):
        raise ValueError("Choose one new distinct seed per repeat, excluding previously used seeds.")
    settings = {"study_id": study_id, "config": asdict(study.config), "sample_counts": counts,
                "seeds": seeds, "metric": METRIC, "noise_model": NOISE_MODEL}
    if any(run["metadata"]["convergence"]["study"] != settings for run in matching):
        raise ValueError("Study settings changed; use a new study_id or restore the original settings.")
    exact_path = directory / f"run_{study_id}_exact.json"
    if exact_path.exists():
        exact_record = json.loads(exact_path.read_text())
    elif any(run["backend"] == "aer_exact" for run in matching):
        existing_exact = next(run for run in matching if run["backend"] == "aer_exact")
        exact_record = json.loads(Path(existing_exact["filepath"]).read_text())
    elif matching:
        # A copied sampled result includes everything needed to resume its study.
        exact_record = matching[0]["metadata"]["convergence"]["exact_reference"]["record"]
    else:
        print("Computing the exact reference…", flush=True)
        exact_config = replace(study.config, n_samples=None)
        exact = ExactBackend().run(exact_config)
        exact_record = make_run_record(exact, exact_config, metadata={"convergence": {
            "study": settings, "role": "exact", "metric": METRIC}})
        write_run_json(exact_record, exact_path)
    reference = {"sha256": reference_digest(exact_record), "record": exact_record}
    _validate_reference(reference, study.config)
    # Existing samples must agree with the exact record before any additional work.
    for run in matching:
        if run["backend"] == "aer_sampling":
            _measurement(run, study.config)
            if run["metadata"]["convergence"]["exact_reference"]["sha256"] != reference["sha256"]:
                raise ValueError("Incompatible convergence exact reference for existing samples")
    for seed in seeds:
        for count in counts:
            path = directory / f"run_{study_id}_seed{seed}_n{count}.json"
            existing = [run for run in matching if run["seed"] == seed and run["n_samples"] == count
                        and run["backend"] == "aer_sampling"]
            if len(existing) > 1:
                raise ValueError("Duplicate convergence measurements for the same study, seed and count")
            if existing:
                print(f"Reusing seed={seed}, trajectories={count:,}", flush=True)
                continue
            config = replace(study.config, seed=seed, n_samples=count)
            print(f"Running seed={seed}, trajectories={count:,} across {len(config.p_list)} probabilities…", flush=True)
            sampled = SamplingBackend().run(config)
            if sampled.metadata.get("seed") != seed or sampled.metadata.get("n_samples") != count:
                raise ValueError("Sampling backend did not use the requested seed and trajectory count.")
            errors = fidelity_error(sampled.fidelities, exact_record["fidelities"], config.p_list)
            record = make_run_record(sampled, config, metadata={"convergence": {
                "study": settings, "role": "sampled", "metric": METRIC,
                "exact_reference": reference, "errors_per_receiver": errors.tolist()}})
            write_run_json(record, path)
            print(f"Saved {path.name}: total error={errors.sum():.6g}", flush=True)
    return study_id
