"""Self-contained SLURM job JSONs with an embedded immutable source snapshot."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@contextmanager
def _locked(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _write(document, path):
    payload = (json.dumps(document, indent=2, allow_nan=False) + "\n").encode()
    return _write_bytes(payload, path)


def _write_bytes(payload, path):
    """Atomically persist exact evidence bytes, including their original format."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".hpc-", suffix=".json", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def _source_snapshot(source_dir):
    paths = sorted(path for folder in ("broadcasting", "hpc")
                   for path in (source_dir / folder).rglob("*")
                   if path.is_file() and path.suffix in {".py", ".sh"} and "__pycache__" not in path.parts)
    requirements = source_dir / "requirements.txt"
    if requirements.is_file():
        paths.append(requirements)
    buffer = io.BytesIO()
    hashes = {}
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in paths:
            relative = str(path.relative_to(source_dir))
            payload = path.read_bytes()
            hashes[relative] = hashlib.sha256(payload).hexdigest()
            information = tarfile.TarInfo(relative)
            information.size, information.mode, information.mtime = len(payload), path.stat().st_mode & 0o777, 0
            archive.addfile(information, io.BytesIO(payload))
    payload = buffer.getvalue()
    revision = None
    head = source_dir / ".git/HEAD"
    if head.is_file():
        ref = head.read_text().strip()
        ref_file = source_dir / ".git" / ref.removeprefix("ref: ")
        revision = ref_file.read_text().strip() if ref.startswith("ref: ") and ref_file.is_file() else None if ref.startswith("ref: ") else ref
    return {"archive_format": "tar.gz", "archive_base64": base64.b64encode(payload).decode("ascii"),
            "archive_sha256": hashlib.sha256(payload).hexdigest(), "source_sha256": hashes, "code_revision": revision}


def load_hpc_job(path):
    document = json.loads(Path(path).read_text())
    if document.get("document_type") != "hpc_execution" or document.get("schema_version") != 3:
        raise ValueError("Expected a self-contained HPC execution JSON.")
    if _digest(document["prepared"]) != document["prepared_sha256"]:
        raise ValueError("HPC preparation checksum mismatch.")
    if document["state"] not in {"prepared", "running", "completed"}:
        raise ValueError("Unknown HPC execution state.")
    if (type(document["expected_tasks"]) is not int or document["expected_tasks"] < 1
            or (document["state"] == "prepared" and document["measurements"])):
        raise ValueError("Invalid prepared HPC task state.")
    from broadcasting.results import validate_run_record
    indices = []
    for record in document["measurements"]:
        validate_run_record(record)
        execution = record["metadata"]["execution"]
        if execution["experiment_id"] != document["prepared"]["submission_id"]:
            raise ValueError("HPC measurement belongs to another submission.")
        indices.append(execution["sweep_task_index"] if execution["sweep_task_index"] is not None else 0)
    if len(indices) != len(set(indices)) or any(not 0 <= index < document["expected_tasks"] for index in indices):
        raise ValueError("HPC task identities are duplicated or outside the planned grid.")
    if (document["state"] == "completed") != (len(indices) == document["expected_tasks"]):
        raise ValueError("HPC completion does not match its task grid.")
    return document


def prepare_hpc(source_dir, results_dir, submission_id, argv, *, array=True):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", submission_id):
        raise ValueError("Submission ID must be filename-safe.")
    source_dir, results_dir = Path(source_dir), Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"hpc_{submission_id}.json"
    with _locked(results_dir):
        from hpc.run_experiment import _parse_args
        args = _parse_args(argv)
        count = len(args.p_values) if args.p_values is not None else args.p_steps
        expected_tasks = count if array else 1
        if expected_tasks < 1:
            raise ValueError("An HPC experiment needs at least one task.")
        if path.exists():
            existing = load_hpc_job(path)
            if (existing["prepared"]["argv"] != argv or existing["expected_tasks"] != expected_tasks
                    or existing["prepared"]["array"] != array):
                raise ValueError("Submission arguments differ from the frozen job JSON.")
            return path
        prepared = {"submission_id": submission_id, "argv": list(argv), "array": array,
                    "source_snapshot": _source_snapshot(source_dir)}
        document = {"schema_version": 3, "document_type": "hpc_execution", "experiment_kind": "broadcasting",
                    "state": "prepared", "prepared": prepared, "prepared_sha256": _digest(prepared),
                    "expected_tasks": expected_tasks, "measurements": []}
        return _write(document, path)


def extract_source(path, destination):
    document = load_hpc_job(path)
    snapshot = document["prepared"]["source_snapshot"]
    payload = base64.b64decode(snapshot["archive_base64"], validate=True)
    if hashlib.sha256(payload).hexdigest() != snapshot["archive_sha256"]:
        raise ValueError("Embedded source archive checksum mismatch.")
    destination = Path(destination)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        archive.extractall(destination, filter="data")
    for relative, digest in snapshot["source_sha256"].items():
        if hashlib.sha256((destination / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("Extracted source does not match its saved checksum.")
    # This temporary runtime manifest is included in each task's provenance;
    # source bytes remain embedded once in the self-contained job JSON.
    (destination / "source_snapshot.json").write_text(json.dumps(
        {"submission_id": document["prepared"]["submission_id"], "code_revision": snapshot["code_revision"],
         "source_sha256": snapshot["source_sha256"], "archive_sha256": snapshot["archive_sha256"]}))
    return destination


def task_exists(path, task_index):
    index = 0 if task_index is None else task_index
    return any((record["metadata"]["execution"]["sweep_task_index"] or 0) == index
               for record in load_hpc_job(path)["measurements"])


def publish_task(path, record):
    from broadcasting.results import validate_run_record
    validate_run_record(record)
    path = Path(path)
    with _locked(path.parent):
        document = load_hpc_job(path)
        execution = record["metadata"]["execution"]
        index = execution["sweep_task_index"] if execution["sweep_task_index"] is not None else 0
        if document["state"] == "completed" or task_exists(path, index):
            raise FileExistsError("Completed task measurements cannot be overwritten.")
        if execution["requested_argv"] != document["prepared"]["argv"]:
            raise ValueError("Measured task arguments differ from the frozen submission.")
        if execution["experiment_id"] != document["prepared"]["submission_id"] or not 0 <= index < document["expected_tasks"]:
            raise ValueError("Measured task does not match the prepared submission.")
        document["measurements"].append(record)
        document["measurements"].sort(key=lambda item: item["metadata"]["execution"]["sweep_task_index"] or 0)
        document["state"] = "completed" if len(document["measurements"]) == document["expected_tasks"] else "running"
        return _write(document, path)


def merge_result_archives(source_dir, destination_dir):
    """Import new records or append verified HPC progress without replacing evidence.

    Existing standalone records are immutable. A partial HPC archive advances
    only if its frozen preparation and every already saved task are unchanged.
    """
    from broadcasting.results import validate_run_record
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    imported = []
    with _locked(destination_dir):
        for source in sorted(Path(source_dir).glob("*.json")):
            payload = source.read_bytes()
            incoming = json.loads(payload)
            target = destination_dir / source.name
            if incoming.get("document_type") == "hpc_execution":
                incoming = load_hpc_job(source)
                if target.exists():
                    existing = load_hpc_job(target)
                    if existing == incoming:
                        continue
                    if (existing["prepared_sha256"] != incoming["prepared_sha256"]
                            or existing["prepared"] != incoming["prepared"]
                            or existing["expected_tasks"] != incoming["expected_tasks"]):
                        raise ValueError(f"Conflicting frozen HPC preparation: {target}")
                    if existing["state"] == "completed":
                        raise ValueError(f"Completed HPC archive cannot be replaced: {target}")
                    incoming_records = {record["record_id"]: record for record in incoming["measurements"]}
                    if any(incoming_records.get(record["record_id"]) != record for record in existing["measurements"]):
                        raise ValueError(f"Incoming archive changed or removed an existing task: {target}")
            else:
                # Preserve previously fetched immutable standalone records,
                # including byte-for-byte source evidence from older runs.
                if target.exists():
                    continue
                if incoming.get("document_type") == "execution":
                    from broadcasting.experiments import load_experiment
                    load_experiment(source)
                else:
                    validate_run_record(incoming)
            if source.read_bytes() != payload:
                raise ValueError(f"Source archive changed during validation: {source}")
            imported.append(_write_bytes(payload, target))
    return imported


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--source-dir", type=Path, required=True)
    prepare.add_argument("--results-dir", type=Path, required=True)
    prepare.add_argument("--submission-id", required=True)
    prepare.add_argument("--single", action="store_true")
    prepare.add_argument("arguments", nargs=argparse.REMAINDER)
    extract = sub.add_parser("extract")
    extract.add_argument("file", type=Path)
    extract.add_argument("destination", type=Path)
    merge = sub.add_parser("merge-dir", help="Import new JSONs and verified HPC progress")
    merge.add_argument("source", type=Path)
    merge.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        print(prepare_hpc(args.source_dir, args.results_dir, args.submission_id, arguments, array=not args.single))
    elif args.command == "extract":
        extract_source(args.file, args.destination)
    else:
        for path in merge_result_archives(args.source, args.destination):
            print(path)


if __name__ == "__main__":
    main()
