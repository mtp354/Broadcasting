"""Merge single-point SLURM array outputs into one sweep record for plotting.

`hpc/run_experiment.py` writes one JSON file per array task when
`SLURM_ARRAY_TASK_ID` is set (each task computes a single noise-probability
point via `p_list=[float(p_full[idx])]`). Nothing else assembles these
per-task files back into the multi-point sweep record that `broadcasting.plotting`
expects. This script does that merge, read-only: it never modifies or deletes
the source per-task files, and writes exactly one new merged JSON file.

Usage
-----
    python scripts/merge_hpc_runs.py results/run_2026*.json --output-dir results

Files are grouped by a config fingerprint (M, N, alpha, use_qec, backend,
n_samples, seed) so a directory containing results from more than one
experiment is handled safely -- one merged file is written per distinct group,
and any group with only one file is skipped (nothing to merge, avoids
generating a spurious "merged" copy of a single un-swept run).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from broadcasting.results import load_run


def _fingerprint(run: dict[str, Any]) -> tuple:
    return (
        run["M"],
        run["N"],
        run.get("alpha"),
        run.get("use_qec"),
        run.get("backend"),
        run.get("n_samples"),
        run.get("seed"),
    )


def _merge_group(paths: list[Path]) -> dict[str, Any]:
    """Merge one group of same-config, single-point runs into a sweep record."""
    raws = []
    for p in paths:
        with open(p) as f:
            raws.append(json.load(f))

    points = []
    for raw, path in zip(raws, paths):
        values = raw["sweep"]["values"]
        fids = raw["fidelities"]
        if len(values) != 1 or len(fids) != 1:
            raise ValueError(
                f"{path.name} is not a single-point sweep file "
                f"(sweep has {len(values)} points) -- only merge per-task "
                "SLURM array outputs, not already-merged sweeps."
            )
        points.append((values[0], fids[0], path.name))

    points.sort(key=lambda t: t[0])
    seen_values = [p[0] for p in points]
    if len(set(seen_values)) != len(seen_values):
        dupes = sorted({v for v in seen_values if seen_values.count(v) > 1})
        raise ValueError(f"Duplicate sweep values found across files: {dupes}")

    base = raws[0]
    merged = dict(base)
    merged["sweep"] = {"axis": base["sweep"]["axis"], "values": [p[0] for p in points]}
    merged["fidelities"] = [p[1] for p in points]
    merged["timestamp"] = datetime.now().isoformat()
    merged.setdefault("metadata", {})
    merged["metadata"] = dict(merged.get("metadata") or {})
    merged["metadata"]["merged_from"] = [p[2] for p in points]
    return merged


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="Per-task result JSON files to merge (glob-expanded by your shell).")
    parser.add_argument("--output-dir", type=str, default="results", help="Directory to write the merged file(s) into.")
    args = parser.parse_args(argv)

    paths = sorted(Path(f) for f in args.files)
    if not paths:
        print("No input files given.")
        return

    groups: dict[tuple, list[Path]] = defaultdict(list)
    for path in paths:
        run = load_run(path)
        if run["experiment_type"] != "simulation" or run["sweep"]["axis"] != "p":
            print(f"Skipping {path.name}: not a p-sweep simulation run.")
            continue
        groups[_fingerprint(run)].append(path)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for fingerprint, group_paths in groups.items():
        if len(group_paths) < 2:
            print(f"Skipping group {fingerprint}: only {len(group_paths)} file(s), nothing to merge.")
            continue

        merged = _merge_group(group_paths)
        out_path = output_dir / f"run_merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
        with open(out_path, "w") as f:
            json.dump(merged, f, indent=2)
        print(
            f"Merged {len(group_paths)} files ({fingerprint}) -> {out_path} "
            f"({len(merged['sweep']['values'])} sweep points)"
        )


if __name__ == "__main__":
    main()
