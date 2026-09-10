"""Detect duplicate hardware measurements before analysis and figure generation.

These helpers filter loaded records without modifying the saved result files.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _record_identity(run: dict[str, Any]) -> str | None:
    """One physical experiment kind and case within an executed job."""
    job_id = run.get("job_id")
    if not job_id:
        return None
    kind = run.get("experiment_kind", "broadcasting")
    execution = (run.get("metadata") or {}).get("execution", {})
    identity = f"{kind} / {job_id}"
    if execution.get("case_id") is not None:
        identity += f" / {execution['case_id']}"
    return identity


def find_duplicate_jobs(runs: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Find repeated saves of one job/case; retain distinct cases in shared jobs."""
    by_record: dict[str, list[str]] = defaultdict(list)
    for run in runs:
        identity = _record_identity(run)
        if identity:
            by_record[identity].append(run.get("filename", run.get("filepath", "?")))
    return {identity: files for identity, files in by_record.items() if len(files) > 1}


def dedupe_by_job(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate saves of the same job/case, keeping the first record.

    Separate experiment cases can share a job; retaining them does not make them
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
