"""Merge complete simulation sweeps from flat result or HPC job JSON files.

Usage: python -m broadcasting.merge_hpc_runs results/hpc_<submission>.json
Records without a requested grid require --expected-p-values. Input subsets must
cover that grid exactly once. Saved results include their source evidence.
"""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

import numpy as np

from .results import (RESULTS_DIR, configuration_from_record, load_runs,
                      validate_run_record, write_run_json)


@dataclass
class _Input:
    run: dict[str, Any]
    path: Path
    sha256: str


def _execution(run):
    metadata = run.get("metadata") or {}
    return metadata.get("execution", {key: metadata[key] for key in
                         ("experiment_id", "requested_sweep_values", "sweep_task_index", "slurm_job_id", "slurm_array_job_id")
                         if key in metadata})


def _json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _snapshot(run):
    return (run.get("execution_record", {}).get("prepared", {}).get("source_snapshot")
            or _execution(run).get("source_snapshot"))


def _check_source(run):
    document = run.get("execution_record", {})
    if document:
        if document.get("document_type") != "hpc_execution":
            raise ValueError("Only standalone simulations or HPC execution documents can be merged.")
        prepared = document["prepared"]
        if _json_digest(prepared) != document.get("prepared_sha256"):
            raise ValueError("HPC preparation checksum mismatch.")
        if _execution(run).get("experiment_id") != prepared.get("submission_id"):
            raise ValueError("Task belongs to a different HPC submission.")
        requested = _execution(run).get("requested_argv")
        if requested is not None and requested != prepared.get("argv"):
            raise ValueError("Task arguments disagree with its HPC preparation.")
    snapshot = _snapshot(run)
    if snapshot:
        encoded = snapshot.get("archive_base64")
        if encoded is not None:
            try:
                digest = hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest()
            except ValueError as error:
                raise ValueError("Invalid embedded source archive.") from error
            if digest != snapshot.get("archive_sha256"):
                raise ValueError("Embedded source archive checksum mismatch.")
        software = (run.get("metadata") or {}).get("software") or {}
        recorded_hashes = software.get("source_sha256")
        archived_hashes = snapshot.get("source_sha256") or {}
        archived_code = {path for path in archived_hashes if Path(path).suffix in {".py", ".sh"}}
        if ((recorded_hashes is not None and
             (any(archived_hashes.get(path) != digest for path, digest in recorded_hashes.items())
              or not archived_code.issubset(recorded_hashes)))
                or (software.get("code_revision") is not None
                    and software["code_revision"] != snapshot.get("code_revision"))):
            raise ValueError("Task source evidence differs from its embedded source snapshot.")


def _fingerprint(run):
    """Settings, submission and source identity that must match across subsets."""
    software = (run.get("metadata") or {}).get("software") or {}
    snapshot = _snapshot(run) or {}
    identity = {key: run.get(key) for key in
                ("schema_version", "experiment_kind", "experiment_type", "backend", "n_samples",
                 "seed", "optimization_level", "shots", "protocol")}
    identity.update(sweep_axis=run["sweep"]["axis"], sweep_unit=run["sweep"].get("unit"),
                    experiment_id=_execution(run).get("experiment_id"),
                    requested_sweep_values=_execution(run).get("requested_sweep_values"),
                    requested_argv=_execution(run).get("requested_argv"),
                    software={"python": software.get("python"), "dependencies": software.get("dependencies"),
                              "code_revision": software.get("code_revision", snapshot.get("code_revision")),
                              "source_sha256": software.get("source_sha256", {
                                  path: digest for path, digest in (snapshot.get("source_sha256") or {}).items()
                                  if Path(path).suffix in {".py", ".sh"}})})
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _requested_grid(run, expected_values):
    planned = _execution(run).get("requested_sweep_values")
    if expected_values is not None:
        if planned is not None and list(expected_values) != planned:
            raise ValueError("Expected grid disagrees with the recorded requested sweep.")
        planned = list(expected_values)
    if (not isinstance(planned, list) or not planned
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in planned)
            or not np.isfinite(planned).all() or any(not 0 <= value <= 1 for value in planned)
            or len(set(planned)) != len(planned)):
        raise ValueError("A nonempty unique intended probability grid is required; "
                         "supply --expected-p-values if it was not recorded.")
    return planned


def _load_inputs(paths):
    inputs = []
    for path in paths:
        path = Path(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        runs = load_runs(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Input changed while being read: {path}")
        if not runs:
            raise ValueError(f"No completed measurements to merge: {path}")
        for run in runs:
            if run["experiment_type"] != "simulation" or run["sweep"]["axis"] != "p":
                raise ValueError("Only p-sweep simulation records can be merged.")
            _check_source(run)
            inputs.append(_Input(run, path, digest))
    return inputs


def _common_dict(dictionaries):
    """Store matching nested metadata once; retain task differences separately."""
    common = {}
    for key in dictionaries[0]:
        if not all(key in item for item in dictionaries):
            continue
        values = [item[key] for item in dictionaries]
        if all(isinstance(value, dict) for value in values):
            shared = _common_dict(values)
            if shared:
                common[key] = shared
        elif all(value == values[0] for value in values):
            common[key] = deepcopy(values[0])
    return common


def _difference(value, common):
    result = {}
    for key, item in value.items():
        if key not in common:
            result[key] = deepcopy(item)
        elif isinstance(item, dict) and isinstance(common[key], dict):
            nested = _difference(item, common[key])
            if nested:
                result[key] = nested
        elif item != common[key]:
            result[key] = deepcopy(item)
    return result


def _merge_records(inputs, expected_values=None):
    if not inputs:
        raise ValueError("No records to merge.")
    runs = [item.run for item in inputs]
    if len({_fingerprint(run) for run in runs}) != 1:
        raise ValueError("Cannot merge different experiment configurations, submissions or sources.")
    snapshots = [_snapshot(run) for run in runs if _snapshot(run)]
    if snapshots and any(snapshot != snapshots[0] for snapshot in snapshots[1:]):
        raise ValueError("Cannot merge different archived source evidence.")
    base = runs[0]
    planned = _requested_grid(base, expected_values)
    points = {}
    for item in inputs:
        run = item.run
        values = run["sweep"]["values"]
        index = _execution(run).get("sweep_task_index")
        if index is not None and (not isinstance(index, int) or isinstance(index, bool)
                                  or len(values) != 1 or not 0 <= index < len(planned)
                                  or planned[index] != values[0]):
            raise ValueError(f"{item.path.name} has inconsistent array-task provenance.")
        for j, value in enumerate(values):
            if value in points:
                raise ValueError(f"Duplicate sweep value {value}.")
            if value not in planned:
                raise ValueError(f"Unexpected sweep value {value}.")
            points[value] = (run, j)
    missing = [value for value in planned if value not in points]
    if missing:
        raise ValueError(f"Incomplete sweep; missing requested values: {missing}")
    # Every optional grid must have consistent availability; never discard counts
    # or reference measurements because only some subsets recorded them.
    for field in ("counts", "per_theta_fidelities"):
        if len({run.get(field) is None for run in runs}) != 1:
            raise ValueError(f"Inconsistent availability of {field} across input subsets.")
    reference_keys = set(base.get("reference_fidelities") or {})
    if any(set(run.get("reference_fidelities") or {}) != reference_keys for run in runs):
        raise ValueError("Inconsistent reference grids across input subsets.")
    fields = ("schema_version", "experiment_kind", "experiment_type", "backend", "optimization_level",
              "job_id", "shots", "seed", "n_samples", "protocol")
    merged = {key: deepcopy(base[key]) for key in fields if key in base}
    merged.update(record_id=uuid.uuid4().hex, timestamp=datetime.now().isoformat(),
                  sweep={**base["sweep"], "values": planned},
                  fidelities=[deepcopy(points[value][0]["fidelities"][points[value][1]]) for value in planned])
    for field in ("counts", "per_theta_fidelities"):
        merged[field] = None if base.get(field) is None else [
            [deepcopy(points[value][0][field][theta][points[value][1]]) for value in planned]
            for theta in range(len(base["protocol"]["theta_samples"]))]
    if reference_keys:
        merged["reference_fidelities"] = {key: [deepcopy(points[value][0]["reference_fidelities"][key][points[value][1]])
                                               for value in planned] for key in sorted(reference_keys)}
    shared = _common_dict([run.get("metadata") or {} for run in runs])
    for key in ("sweep_task_index", "slurm_job_id", "sources", "input_records", "input_jobs", "sweep_complete"):
        shared.get("execution", {}).pop(key, None)
        shared.pop(key, None)
    merged["metadata"] = deepcopy(shared)
    execution = merged["metadata"].setdefault("execution", {})
    execution.update(requested_sweep_values=planned, sweep_complete=True,
                     sources=[{"path": str(item.path), "record_id": item.run["record_id"], "sha256": item.sha256}
                              for item in inputs],
                     input_records=[{"record_id": run["record_id"], "timestamp": run.get("timestamp"),
                                     "job_id": run.get("job_id"), "sweep_values": run["sweep"]["values"],
                                     "metadata": _difference(run.get("metadata") or {}, shared)} for run in runs])
    # Submission/source bytes are embedded once, independently of source filenames.
    if snapshots:
        execution["source_snapshot"] = deepcopy(snapshots[0])
    documents = {}
    for item in inputs:
        document = item.run.get("execution_record")
        if document and item.sha256 not in documents:
            prepared = {key: deepcopy(value) for key, value in document["prepared"].items() if key != "source_snapshot"}
            documents[item.sha256] = {**{key: deepcopy(value) for key, value in document.items() if key != "prepared"},
                                       "prepared": prepared, "source_file_sha256": item.sha256}
    if documents:
        execution["input_jobs"] = list(documents.values())
    merged["config"] = configuration_from_record(merged)
    validate_run_record(merged)
    return merged


def _merge_group(paths: list[Path], expected_values: list[float] | None = None) -> dict[str, Any]:
    """Merge inputs covering one complete experiment, including embedded job tasks."""
    return _merge_records(_load_inputs(paths), expected_values)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output-dir", default=str(RESULTS_DIR))
    destination.add_argument("--output", type=Path, help="Exact output path for one merged experiment; never overwritten.")
    parser.add_argument("--expected-p-values", type=float, nargs="+")
    args = parser.parse_args(argv)
    groups = defaultdict(list)
    for item in _load_inputs(sorted(Path(name) for name in args.files)):
        groups[_fingerprint(item.run)].append(item)
    merged_groups = [_merge_records(inputs, args.expected_p_values) for inputs in groups.values()]
    if args.output is not None and len(merged_groups) != 1:
        parser.error("--output requires inputs from exactly one experiment")
    for merged in merged_groups:
        output = args.output or Path(args.output_dir) / f"run_merged_{uuid.uuid4().hex}.json"
        write_run_json(merged, output)
        print(f"Merged {len(merged['sweep']['values'])} complete sweep points -> {output}")


if __name__ == "__main__":
    main()
