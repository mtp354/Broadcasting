"""Merge complete, same-experiment single-point SLURM outputs without overwrite.

Usage: python scripts/merge_hpc_runs.py results/records/run_*.json
Records lacking a requested sweep require --expected-p-values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from broadcasting.results import load_run, validate_run_record, write_run_json


def _execution(run):
    metadata = run.get("metadata") or {}
    # Migrated records retain their original task fields; new runs group them
    # under execution alongside other experiment entrypoints.
    return metadata.get("execution", {key: metadata[key] for key in
                         ("experiment_id", "requested_sweep_values", "sweep_task_index", "slurm_job_id", "slurm_array_job_id")
                         if key in metadata})


def _fingerprint(run: dict[str, Any]) -> str:
    """Include every setting that must match across independently saved tasks."""
    metadata = run.get("metadata") or {}
    protocol_fields = ("M", "N", "alpha", "use_qec", "theta_samples",
                       "linear_feedforward", "outcomes_list")
    protocol = run.get("protocol") or {key: run.get(key) for key in protocol_fields}
    software = metadata.get("software") or {}
    run_fields = ("schema_version", "experiment_kind", "experiment_type", "backend", "n_samples", "seed",
                  "optimization_level", "shots")
    identity = {
        **{key: run.get(key) for key in run_fields},
        "protocol": protocol,
        "sweep_axis": run["sweep"]["axis"],
        "experiment_id": _execution(run).get("experiment_id"),
        "requested_sweep_values": _execution(run).get("requested_sweep_values"),
        "code_revision": software.get("code_revision"),
        "source_sha256": software.get("source_sha256"),
        "dependencies": software.get("dependencies"),
    }
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _requested_grid(run, expected_values):
    planned = _execution(run).get("requested_sweep_values")
    if expected_values is not None:
        if planned is not None and list(expected_values) != planned:
            raise ValueError("Expected grid disagrees with the recorded requested sweep.")
        planned = list(expected_values)
    if not planned or len(set(planned)) != len(planned):
        raise ValueError("A nonempty unique intended sweep is required; "
                         "supply --expected-p-values if it was not recorded.")
    return planned


def _merge_group(paths: list[Path], expected_values: list[float] | None = None) -> dict[str, Any]:
    """Require equal experiment fingerprints and exactly the intended points."""
    if not paths:
        raise ValueError("No records to merge.")
    raws = [json.loads(Path(path).read_text()) for path in paths]
    for raw in raws:
        validate_run_record(raw)
    if len({_fingerprint(raw) for raw in raws}) != 1:
        raise ValueError("Cannot merge different experiment configurations or submissions.")
    base = raws[0]
    if base["experiment_type"] != "simulation" or base["sweep"]["axis"] != "p":
        raise ValueError("Only p-sweep simulation records can be merged.")
    planned = _requested_grid(base, expected_values)
    points = {}
    for raw, path in zip(raws, paths):
        values, fids = raw["sweep"]["values"], raw["fidelities"]
        if len(values) != 1 or len(fids) != 1:
            raise ValueError(f"{path.name} is not a single-point sweep file.")
        value = values[0]
        if value in points:
            raise ValueError(f"Duplicate sweep value {value}.")
        if len(fids[0]) != base["protocol"]["N"]:
            raise ValueError(f"{path.name} has an invalid receiver-fidelity shape.")
        if value not in planned:
            raise ValueError(f"Unexpected sweep value {value}.")
        task_index = _execution(raw).get("sweep_task_index")
        if task_index is not None and (not 0 <= task_index < len(planned) or planned[task_index] != value):
            raise ValueError(f"{path.name} has inconsistent array-task provenance.")
        if raw.get("per_theta_fidelities") is not None or len(base["protocol"]["theta_samples"]) != 1:
            raise ValueError("Per-task multi-theta records require an explicit merge implementation.")
        points[value] = (fids[0], path.name, raw.get("metadata", {}),
                         {"path": str(path), "record_id": raw["record_id"],
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    missing = [value for value in planned if value not in points]
    if missing:
        raise ValueError(f"Incomplete sweep; missing requested values: {missing}")
    merged = dict(base)
    merged.update(
        record_id=uuid.uuid4().hex,
        sweep={**base["sweep"], "values": planned},
        fidelities=[points[value][0] for value in planned],
        timestamp=datetime.now().isoformat(),
    )
    merged["metadata"] = dict(base.get("metadata") or {})
    execution = dict(_execution(base))
    execution.pop("sweep_task_index", None)
    execution.pop("slurm_job_id", None)
    execution.update(
        merged_from=[points[value][1] for value in planned],
        requested_sweep_values=planned,
        sweep_complete=True,
        task_metadata=[points[value][2] for value in planned],
        sources=[points[value][3] for value in planned],
    )
    # Keep one authoritative location for task/submission fields in new merges.
    for key in ("experiment_id", "requested_sweep_values", "sweep_task_index", "slurm_job_id", "slurm_array_job_id"):
        merged["metadata"].pop(key, None)
    merged["metadata"]["execution"] = execution
    validate_run_record(merged)
    return merged


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--output-dir", default="results/records")
    parser.add_argument("--expected-p-values", type=float, nargs="+")
    args = parser.parse_args(argv)
    groups = defaultdict(list)
    for path in sorted(Path(name) for name in args.files):
        run = load_run(path)
        if run["experiment_type"] != "simulation" or run["sweep"]["axis"] != "p":
            raise ValueError(f"{path}: expected a p-sweep simulation.")
        groups[_fingerprint(run)].append(path)
    # Validate all groups before publishing any outputs.
    merged_groups = [_merge_group(paths, args.expected_p_values) for paths in groups.values()]
    for merged in merged_groups:
        output = Path(args.output_dir) / f"run_merged_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex}.json"
        write_run_json(merged, output)
        print(f"Merged {len(merged['sweep']['values'])} complete sweep points -> {output}")


if __name__ == "__main__":
    main()
