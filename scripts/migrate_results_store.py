#!/usr/bin/env python3
"""One-time, offline conversion of saved inputs into the measured-result store.

Original bytes and execution bundles are first preserved in an immutable gzip
archive. Source files are never deleted. Re-running verifies existing outputs
instead of replacing them. Old-format knowledge is confined to this migration.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from broadcasting.results import SCHEMA_VERSION, load_run, validate_run_record, write_run_json


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(left, right, message: str) -> None:
    if left != right:
        raise ValueError(message)


def preserve_archive(root: Path, inputs: list[Path], archive: Path) -> dict:
    """Publish an exclusive archive and verify every member against its source."""
    inventory = {str(path.relative_to(root)): digest(path) for path in inputs}
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(dir=archive.parent, suffix=".tar.gz.tmp")
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with tarfile.open(temporary, "w:gz", compresslevel=6) as bundle:
                for path in inputs:
                    bundle.add(path, arcname=str(path.relative_to(root)), recursive=False)
                payload = json.dumps({"source_sha256": inventory}, indent=2).encode()
                entry = tarfile.TarInfo("SOURCE_MANIFEST.json")
                entry.size = len(payload)
                bundle.addfile(entry, io.BytesIO(payload))
            os.link(temporary, archive)
            archive.chmod(0o444)
        finally:
            temporary.unlink(missing_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        manifest = json.load(bundle.extractfile("SOURCE_MANIFEST.json"))
        for relative, expected in inventory.items():
            equal(manifest["source_sha256"].get(relative), expected,
                  f"Archive source changed: {relative}")
            archived = hashlib.sha256(bundle.extractfile(relative).read()).hexdigest()
            equal(archived, expected, f"Archive content differs: {relative}")
    return {"path": str(archive.relative_to(root)), "sha256": digest(archive),
            "source_count": len(inventory), "source_sha256": inventory}


def apply_attributions(record: dict, spec: dict, relative: str) -> None:
    attributions = spec.get("historical_overrides", {})
    for field, attribution in attributions.items():
        if not attribution.get("evidence"):
            raise ValueError(f"Attribution has no evidence: {relative}: {field}")
        target = record["metadata"] if field == "dt" else record["protocol"]
        if target.get(field) is None:
            target[field] = attribution["value"]
        else:
            equal(target[field], attribution["value"], f"Conflicting attribution: {relative}: {field}")
    if attributions:
        record["metadata"].setdefault("provenance", {})["attributions"] = copy.deepcopy(attributions)


def normalize(raw: dict, relative: str, spec: dict) -> dict:
    """Convert either measured input schema without recomputing its values."""
    if "experiment_type" in raw and "sweep" in raw:
        record = copy.deepcopy(raw)
        record["experiment_kind"] = "broadcasting"
        record["sweep"]["unit"] = "dt" if record["sweep"]["axis"] == "tau" else "probability"
    elif raw.get("experiment") == "qec_513_delay_sweep":
        preparation = copy.deepcopy(raw["state_prep"])
        record = {
            "experiment_kind": "memory", "timestamp": raw["timestamp"],
            "experiment_type": "hardware", "backend": raw["backend"],
            "optimization_level": raw.get("optimization_level"), "job_id": raw.get("job_id"),
            "shots": raw.get("shots"), "seed": raw.get("seed"), "n_samples": None,
            "protocol": {"M": 0, "N": 1, "alpha": None, "use_qec": raw.get("use_qec"),
                         "theta_samples": [[preparation["theta"], preparation["phi"]]],
                         "state_prep": preparation, "linear_feedforward": None, "outcomes_list": None},
            "sweep": {"axis": "tau", "unit": "dt", "values": raw["tau_values"]},
            "fidelities": [[value] for value in raw["backend_fidelities"]],
            "per_theta_fidelities": None,
            "counts": None if raw.get("backend_counts") is None else [raw["backend_counts"]],
            "metadata": copy.deepcopy(raw.get("metadata", {})),
        }
        if raw.get("ideal_fidelities") is not None:
            record["reference_fidelities"] = {"ideal": [[value] for value in raw["ideal_fidelities"]]}
    else:
        raise ValueError(f"No measured-input conversion for {relative}")
    metadata = record.setdefault("metadata", {})
    grouping = metadata.pop("campaign", None)
    if grouping:
        execution = metadata.setdefault("execution", {})
        for key, value in grouping.items():
            key = "experiment_id" if key == "campaign_id" else key
            if key in execution:
                equal(execution[key], value, f"Conflicting execution {key}: {relative}")
            execution[key] = value
    apply_attributions(record, spec, relative)
    record["schema_version"] = SCHEMA_VERSION
    record["record_id"] = hashlib.sha256(relative.encode()).hexdigest()[:24]
    validate_run_record(record)
    return record


def check_converted_source(raw: dict, canonical: dict, relative: str) -> None:
    """Assert exact equality for every stored measurement and configuration."""
    if canonical["experiment_kind"] == "memory":
        equal(raw["tau_values"], canonical["sweep"]["values"], f"Changed memory grid: {relative}")
        equal(raw["backend_fidelities"], [row[0] for row in canonical["fidelities"]],
              f"Changed memory fidelities: {relative}")
        equal(raw.get("backend_counts"), None if canonical["counts"] is None else canonical["counts"][0],
              f"Changed memory counts: {relative}")
        equal(raw.get("ideal_fidelities"),
              None if "reference_fidelities" not in canonical else
              [row[0] for row in canonical["reference_fidelities"]["ideal"]],
              f"Changed memory reference: {relative}")
        equal(raw["state_prep"], canonical["protocol"]["state_prep"], f"Changed state preparation: {relative}")
    else:
        for field in ["fidelities", "per_theta_fidelities", "counts", "protocol"]:
            equal(raw.get(field), canonical.get(field), f"Changed broadcasting {field}: {relative}")
        equal(raw["sweep"]["values"], canonical["sweep"]["values"], f"Changed probability/delay grid: {relative}")
        equal(raw["sweep"]["axis"], canonical["sweep"]["axis"], f"Changed sweep axis: {relative}")
        # Every non-grouping source metadata field, including large shot/QPY
        # payloads, must survive exactly. Reference hashes are adapted later.
        for field, value in raw.get("metadata", {}).items():
            if field not in {"campaign", "execution", "provenance"}:
                equal(value, canonical["metadata"][field], f"Changed metadata {field}: {relative}")
        for field, value in raw.get("metadata", {}).get("execution", {}).items():
            equal(value, canonical["metadata"]["execution"][field], f"Changed execution {field}: {relative}")
    for field in ["backend", "optimization_level", "job_id", "shots", "seed"]:
        equal(raw.get(field), canonical.get(field), f"Changed {field}: {relative}")


def check_earlier_copy(raw: dict, converted: dict, relative: str) -> None:
    """Verify that an earlier save is exactly represented by its converted copy."""
    protocol = raw["protocol"]
    for field in ["M", "N", "use_qec", "alpha"]:
        if field in protocol:
            equal(protocol[field], converted["protocol"].get(field), f"Earlier-copy protocol mismatch: {relative}: {field}")
    if "results" in raw:
        equal(protocol["tau_values"], converted["sweep"]["values"], f"Earlier-copy delay mismatch: {relative}")
        equal(protocol["theta_samples"], converted["protocol"]["theta_samples"], f"Earlier-copy phases mismatch: {relative}")
        rows = list(raw["results"].values())
        for row in rows:
            ti = row["theta_idx"]
            sj = protocol["tau_values"].index(row["tau"])
            fidelities = converted.get("per_theta_fidelities")
            observed = fidelities[ti][sj] if fidelities is not None else converted["fidelities"][sj]
            equal(row["fidelities"], observed, f"Earlier-copy fidelity mismatch: {relative}")
            equal(row["counts"], converted["counts"][ti][sj], f"Earlier-copy counts mismatch: {relative}")
        equal(len(rows), len(protocol["tau_values"]) * len(protocol["theta_samples"]),
              f"Incomplete earlier-copy grid: {relative}")
    else:
        equal(raw["fidelities"], converted["fidelities"], f"Earlier-copy fidelity mismatch: {relative}")
        equal(protocol["p_list"], converted["sweep"]["values"], f"Earlier-copy probability mismatch: {relative}")
        equal([protocol["thetas"]], converted["protocol"]["theta_samples"], f"Earlier-copy phases mismatch: {relative}")


def measurement_identity(record: dict, relative: str) -> tuple:
    """Collapse only repeated saves of one physical job/case, never simulations."""
    if record.get("job_id"):
        execution = record["metadata"].get("execution", {})
        return record["experiment_kind"], record["job_id"], execution.get("case_id")
    return record["experiment_kind"], relative


def migrate(root: Path, archive_dir: Path, mapping_path: Path, *, apply: bool) -> dict:
    manifest_path = root / "figures/sources.json"
    manifest = json.loads(manifest_path.read_text())
    source_paths = sorted(path for path in (root / "results").rglob("*.json")
                          if "records" not in path.relative_to(root).parts)
    source_paths += sorted((root / "campaigns").glob("*/results/*.json"))
    records: dict[tuple, dict] = {}
    source_to_identity = {}
    earlier = []
    for path in source_paths:
        relative = str(path.relative_to(root))
        if "legacy" in path.parts:
            earlier.append(path)
            continue
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict) or not ("experiment_type" in raw or raw.get("experiment") == "qec_513_delay_sweep"):
            continue
        spec = manifest["runs"].get(relative, {})
        source_sha = digest(path)
        if spec:
            equal(source_sha, spec["sha256"], f"Pinned source changed: {relative}")
        canonical = normalize(raw, relative, spec)
        check_converted_source(raw, canonical, relative)
        identity = measurement_identity(canonical, relative)
        if identity in records:
            existing = records[identity]
            for field in ["protocol", "sweep", "fidelities", "per_theta_fidelities", "counts", "reference_fidelities",
                          "backend", "optimization_level", "shots"]:
                equal(existing.get(field), canonical.get(field), f"Conflicting repeated save: {relative}: {field}")
        else:
            records[identity] = canonical
        sources = records[identity]["metadata"].setdefault("provenance", {}).setdefault("sources", [])
        sources.append({"path": relative, "sha256": source_sha})
        source_to_identity[relative] = identity
    for path in earlier:
        relative = str(path.relative_to(root))
        converted_path = f"results/{path.name}"
        if converted_path not in source_to_identity:
            raise ValueError(f"Earlier input has no converted counterpart: {relative}")
        identity = source_to_identity[converted_path]
        check_earlier_copy(json.loads(path.read_text()), records[identity], relative)
        records[identity]["metadata"]["provenance"]["sources"].append({
            "path": relative, "sha256": digest(path), "relationship": "verified earlier save of same measurement"})
        source_to_identity[relative] = identity
    mapping = {relative: f"results/records/run_{records[identity]['record_id']}.json"
               for relative, identity in source_to_identity.items()}
    summary = {"schema_version": SCHEMA_VERSION, "source_records": len(mapping), "canonical_records": len(records),
               "broadcasting_records": sum(r["experiment_kind"] == "broadcasting" for r in records.values()),
               "memory_records": sum(r["experiment_kind"] == "memory" for r in records.values())}
    if not apply:
        return summary
    archive_inputs = sorted({p for folder in ["results", "campaigns"] for p in (root / folder).rglob("*")
                             if p.is_file() and "records" not in p.relative_to(root).parts
                             and p.name != "migration_v2.json"}
                            | {manifest_path})
    archive = preserve_archive(root, archive_inputs, archive_dir / "before-results-v2.tar.gz")
    summary["archive"] = {k: v for k, v in archive.items() if k != "source_sha256"}
    # Exact reference files are published first so dependent records pin their
    # normalized bytes. The original reference hash remains explicit evidence.
    ordered = sorted(records.values(), key=lambda r: bool(r["metadata"].get("convergence", {}).get("exact_sha256")))
    old_to_new_sha = {}
    for record in ordered:
        provenance = record["metadata"]["provenance"]
        provenance["archive"] = summary["archive"]
        convergence = record["metadata"].get("convergence", {})
        old_exact = convergence.get("exact_sha256")
        if old_exact:
            if old_exact not in old_to_new_sha:
                raise ValueError("Convergence exact reference could not be mapped")
            provenance["reference_sources"] = {"exact_sha256": old_exact}
            convergence["exact_sha256"] = old_to_new_sha[old_exact]
        path = root / f"results/records/run_{record['record_id']}.json"
        validate_run_record(record)
        if path.exists():
            equal(json.loads(path.read_text()), record, f"Existing canonical record differs: {path}")
        else:
            write_run_json(record, path)
        loaded = load_run(path)
        for field in ["fidelities", "per_theta_fidelities", "counts", "protocol", "metadata", "reference_fidelities"]:
            equal(loaded.get(field), record.get(field), f"Canonical round trip changed {field}: {path}")
        for source in provenance["sources"]:
            old_to_new_sha[source["sha256"]] = digest(path)
    # Verify original files again after publication; nothing in this operation
    # may change, move, or delete a source input.
    for relative, sha in archive["source_sha256"].items():
        equal(digest(root / relative), sha, f"Input changed during migration: {relative}")
    mapping_path.write_text(json.dumps(mapping, indent=2) + "\n")
    report_path = root / "results/migration_v2.json"
    report = {**summary, "path_mapping": mapping, "record_sha256": {
        path: digest(root / path) for path in sorted(set(mapping.values()))},
        "verification": "All source measurement arrays, counts, preparation parameters and execution payloads verified exactly; earlier copies matched before deduplication; source files unchanged."}
    if report_path.exists():
        equal(json.loads(report_path.read_text()), report, "Existing migration report differs")
    else:
        write_run_json(report, report_path)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--mapping", type=Path, default=Path("/tmp/broadcast-result-path-map.json"))
    parser.add_argument("--apply", action="store_true", help="Archive and publish verified canonical copies")
    args = parser.parse_args()
    archive_dir = args.archive_dir or args.root / ".local-archive"
    print(json.dumps(migrate(args.root.resolve(), archive_dir.resolve(), args.mapping, apply=args.apply), indent=2))
