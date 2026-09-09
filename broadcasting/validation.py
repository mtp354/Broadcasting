"""Small dataset-validation helpers for reasoning about saved run collections.

Used by the figure-generation notebooks to stratify by backend/shots and to
flag duplicate hardware jobs before any aggregate statistic (mean, scaling
trend, etc.) is computed across them -- read-only, never touches result files.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Hashable


def _record_identity(run: dict[str, Any]) -> str | None:
    """A Runtime job may contain several separately saved campaign cases."""
    job_id = run.get("job_id")
    if not job_id:
        return None
    campaign = (run.get("metadata") or {}).get("campaign")
    if campaign:
        return (f"{job_id} / {campaign['run_id']} / repeat {campaign['repeat_index']} / "
                f"{campaign['case_id']}")
    return job_id


def find_duplicate_jobs(runs: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Find repeated saves of one job/case; retain distinct cases in shared jobs."""
    by_record: dict[str, list[str]] = defaultdict(list)
    for run in runs:
        identity = _record_identity(run)
        if identity:
            by_record[identity].append(run.get("filename", run.get("filepath", "?")))
    return {identity: files for identity, files in by_record.items() if len(files) > 1}


def group_by_cohort(
    runs: list[dict[str, Any]],
    keys: tuple[str, ...] = ("backend", "shots"),
) -> dict[tuple[Hashable, ...], list[dict[str, Any]]]:
    """Group runs by the given top-level keys (e.g. backend, shots).

    Use this before pooling runs into one aggregate plot/statistic, so that
    incomparable cohorts (different backend, different shot count, different
    optimization level, ...) are never silently averaged together.
    """
    groups: dict[tuple[Hashable, ...], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        key = tuple(run.get(k) for k in keys)
        groups[key].append(run)
    return groups


def dedupe_by_job(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate saves of the same job/case, keeping the first record.

    Separate campaign cases can share a job; retaining them does not make them
    independent job repetitions.

    Never deletes or modifies the underlying files -- only filters the
    in-memory list used for an analysis or figure.
    """
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for run in runs:
        identity = _record_identity(run)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        kept.append(run)
    return kept
