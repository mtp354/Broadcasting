"""Offline execution provenance; never requests live backend properties."""
from __future__ import annotations

import base64
from collections import Counter
import hashlib
import importlib.metadata
import io
import json
import platform
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def execution_summary(run: dict) -> dict:
    """Compact execution identity for derived points; full evidence stays in the record."""
    execution = (run.get("metadata") or {}).get("execution") or {}
    fields = ("experiment_id", "run_id", "repeat_index", "case_id", "receiver_delay_factors",
              "protocol_family", "circuit_family", "theta_seed", "submission_id", "array_task_id")
    return {field: execution[field] for field in fields if field in execution}


def _code_revision() -> str | None:
    """Read checkout identity without launching a process during offline planning."""
    git_dir = ROOT / ".git"
    if git_dir.is_file():
        git_dir = (ROOT / git_dir.read_text().strip().removeprefix("gitdir: ")).resolve()
    head = git_dir / "HEAD"
    if not head.exists():
        return None
    reference = head.read_text().strip()
    if not reference.startswith("ref: "):
        return reference  # Detached HEAD.
    reference = reference.removeprefix("ref: ")
    common_dir_file = git_dir / "commondir"
    common_dir = ((git_dir / common_dir_file.read_text().strip()).resolve()
                  if common_dir_file.exists() else git_dir)
    loose_ref = common_dir / reference
    if loose_ref.exists():
        return loose_ref.read_text().strip()
    packed_refs = common_dir / "packed-refs"
    if packed_refs.exists():
        for line in packed_refs.read_text().splitlines():
            if line.endswith(" " + reference):
                return line.split()[0]
    return None


def software_provenance() -> dict:
    """Identify installed dependencies and the exact checked-out source bytes."""
    paths = sorted({p for folder in ("broadcasting", "hpc")
                    for p in (ROOT / folder).rglob("*")
                    if p.suffix in {".py", ".sh"} and p.is_file()})
    versions = {}
    for name in ("numpy", "scipy", "qiskit", "qiskit-aer", "qiskit-ibm-runtime"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    revision = _code_revision()
    # Cluster snapshots have no .git; the submission manifest preserves revision.
    manifest = ROOT / "source_snapshot.json"
    snapshot = json.loads(manifest.read_text()) if manifest.exists() else None
    if revision is None and snapshot:
        revision = snapshot.get("code_revision")
    return {"python": platform.python_version(), "dependencies": versions,
            "code_revision": revision,
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in paths},
            "source_snapshot": snapshot}


def circuit_provenance(circuit, target=None) -> dict:
    """Archive replayable QPY, layout, recursive operation counts and duration."""
    from qiskit import qpy

    buffer = io.BytesIO()
    qpy.dump(circuit, buffer)
    payload = buffer.getvalue()
    layout = getattr(circuit, "layout", None)
    layout_data = None
    if layout is not None:
        layout_data = {"initial_index_layout": layout.initial_index_layout(),
                       "final_index_layout": layout.final_index_layout()}
    duration = None
    duration_note = "No target supplied."
    if target is not None:
        try:
            duration = float(circuit.estimate_duration(target, unit="s"))
            duration_note = "Qiskit target-based estimate; excludes queue and classical latency."
        except Exception as exc:
            # Dynamic control flow and unbound durations have no reliable scalar
            # estimate. Preserve why instead of silently inventing a duration.
            duration_note = f"Unavailable: {type(exc).__name__}: {exc}"
    return {"qpy_base64": base64.b64encode(payload).decode("ascii"),
            "sha256": hashlib.sha256(payload).hexdigest(), "layout": layout_data,
            "num_qubits": circuit.num_qubits, "num_clbits": circuit.num_clbits,
            "depth": circuit.depth(), "operation_counts": dict(_count_operations(circuit)),
            "parameters": sorted(p.name for p in circuit.parameters),
            "duration_seconds": duration, "duration_note": duration_note}


def _count_operations(circuit) -> Counter:
    """Include operations inside dynamic control-flow blocks."""
    counts = Counter()
    for instruction in circuit.data:
        counts[instruction.operation.name] += 1
        for block in getattr(instruction.operation, "blocks", ()):
            counts.update(_count_operations(block))
    return counts


def calibration_provenance(backend, circuits) -> dict:
    """Snapshot relevant properties already present in the transpilation target.

    No backend.properties() call is made. Missing calibration timestamps and
    target properties remain explicit, including on offline/fake targets.
    """
    target = getattr(backend, "target", None)
    if target is None or not hasattr(target, "operation_names"):
        return {"source": "target unavailable", "dt_seconds": getattr(target, "dt", None)}
    used = set()

    def collect(circuit, mapping):
        for instruction in circuit.data:
            qargs = tuple(mapping[circuit.find_bit(q).index] for q in instruction.qubits)
            used.add((instruction.operation.name, qargs))
            for block in getattr(instruction.operation, "blocks", ()):
                collect(block, qargs)

    for circuit in circuits:
        collect(circuit, tuple(range(circuit.num_qubits)))
    gates = []
    for name, qargs in sorted(used):
        if name not in target.operation_names:
            continue
        props = target[name].get(qargs)
        gates.append({"operation": name, "qubits": list(qargs),
                      "duration_seconds": getattr(props, "duration", None),
                      "error": getattr(props, "error", None)})
    qubits = sorted({q for _, qargs in used for q in qargs})
    properties = getattr(target, "qubit_properties", None)
    qubit_data = []
    if properties:
        for q in qubits:
            props = properties[q]
            qubit_data.append({"qubit": q, "t1_seconds": getattr(props, "t1", None),
                               "t2_seconds": getattr(props, "t2", None),
                               "frequency_hz": getattr(props, "frequency", None)})
    cached_props = getattr(backend, "_props_dict", None) or {}
    return {"source": "cached transpilation target; no properties refresh",
            "last_update_date": str(cached_props.get("last_update_date")) if cached_props.get("last_update_date") else None,
            "dt_seconds": getattr(target, "dt", None),
            "timing_constraints": {name: getattr(target, name, None) for name in
                                   ("granularity", "min_length", "pulse_alignment", "acquire_alignment")},
            "instructions": gates, "qubits": qubit_data}
