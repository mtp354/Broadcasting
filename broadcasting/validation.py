"""Small dataset-validation helpers for reasoning about saved run collections.

Used by the figure-generation notebooks to stratify by backend/shots and to
flag duplicate hardware jobs before any aggregate statistic (mean, scaling
trend, etc.) is computed across them -- read-only, never touches result files.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Hashable


def find_duplicate_jobs(runs: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Group run records that share the same non-null ``job_id``.

    Parameters
    ----------
    runs : list[dict]
        Loaded run records (e.g. from :func:`broadcasting.results.list_runs`).

    Returns
    -------
    dict[str, list[str]]
        Mapping from ``job_id`` to the list of filenames sharing it, restricted
        to job IDs that appear more than once (a real duplicate save, not an
        independent repetition).
    """
    by_job: dict[str, list[str]] = defaultdict(list)
    for run in runs:
        job_id = run.get("job_id")
        if job_id:
            by_job[job_id].append(run.get("filename", run.get("filepath", "?")))
    return {job_id: files for job_id, files in by_job.items() if len(files) > 1}


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
    """Return *runs* with duplicate-``job_id`` entries dropped (first kept).

    Never deletes or modifies the underlying files -- only filters the
    in-memory list used for an analysis or figure.
    """
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for run in runs:
        job_id = run.get("job_id")
        if job_id and job_id in seen:
            continue
        if job_id:
            seen.add(job_id)
        kept.append(run)
    return kept
