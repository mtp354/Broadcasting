"""Offline HPC execution with self-contained source/configuration/result JSONs."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from hpc.run_experiment import main
from hpc.archive import extract_source, load_hpc_job, prepare_hpc
from broadcasting.results import list_runs, load_run

ROOT = Path(__file__).resolve().parents[1]


def _run_tasks(tmp_path, monkeypatch, points=(0, 0.1, 1)):
    monkeypatch.setenv("SLURM_ARRAY_JOB_ID", "experiment")
    for index in range(len(points)):
        monkeypatch.setenv("SLURM_ARRAY_TASK_ID", str(index))
        main(["--M", "1", "--N", "1", "--thetas", "0.3", "--outcomes", "0",
              "--seed", "7", "--p-values", *map(str, points), "--output-dir", str(tmp_path)])
    return sorted(tmp_path.glob("run_*.json"))


def test_cli_negative_array_index_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "-1")
    with pytest.raises(SystemExit):
        main(["--p-values", "0", "1", "--output-dir", str(tmp_path)])
    assert not list(tmp_path.iterdir())


def test_local_cli_defaults_to_flat_canonical_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLURM_ARRAY_TASK_ID", raising=False)
    main(["--M", "1", "--N", "1", "--p-values", "0", "--seed", "7"])
    paths = list((tmp_path / "results").iterdir())
    assert len(paths) == 1 and paths[0].suffix == ".json"
    record = load_run(paths[0])
    assert record["schema_version"] == 2
    assert record["fidelities"][0][0] == pytest.approx(1.0, abs=1e-12)


def _source_text(document, path):
    snapshot = document["prepared"]["source_snapshot"]
    payload = base64.b64decode(snapshot["archive_base64"])
    assert hashlib.sha256(payload).hexdigest() == snapshot["archive_sha256"]
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        return archive.extractfile(path).read().decode()


def test_slurm_script_keeps_one_json_and_frozen_source_for_each_submission(tmp_path):
    global_dir, scratch = tmp_path / "global", tmp_path / "scratch"
    global_dir.mkdir()
    scratch.mkdir()
    for folder in ("broadcasting", "hpc"):
        shutil.copytree(ROOT / folder, global_dir / folder, ignore=shutil.ignore_patterns("__pycache__"))
    marker = global_dir / "hpc/snapshot_marker.py"
    first = "generation = 'first'\n"
    marker.write_text(first)
    (scratch / ".venv").symlink_to(Path(sys.executable).parent.parent, target_is_directory=True)
    shell_init = tmp_path / "shell_init.sh"
    shell_init.write_text("module() { :; }\nexport -f module\n")
    runtime_tmp = tmp_path / "runtime"
    runtime_tmp.mkdir()
    env = dict(os.environ, BROADCAST_GLOBAL_DIR=str(global_dir), BROADCAST_SCRATCH_DIR=str(scratch),
               TMPDIR=str(runtime_tmp), BASH_ENV=str(shell_init), M="1", N="1", MODE="exact", THETAS="0.3",
               OUTCOMES="0", SEED="7", P_LIST="0 0.1 1", SLURM_ARRAY_JOB_ID="123")
    for task in range(3):
        env.update(SLURM_ARRAY_TASK_ID=str(task), SLURM_JOB_ID=f"123{task}")
        subprocess.run(["bash", str(ROOT / "hpc/slurm_broadcast.sh")], env=env,
                       capture_output=True, text=True, check=True)
        document = load_hpc_job(global_dir / "results/hpc_123.json")
        assert len(document["measurements"]) == task + 1
        assert len(list_runs(global_dir / "results")) == task + 1
        assert not list(runtime_tmp.iterdir())
        marker.write_text("generation = 'second'\n")
    document = load_hpc_job(global_dir / "results/hpc_123.json")
    assert document["state"] == "completed"
    assert _source_text(document, "hpc/snapshot_marker.py") == first
    assert all(run["metadata"]["software"]["source_sha256"]["hpc/snapshot_marker.py"] == hashlib.sha256(first.encode()).hexdigest()
               for run in document["measurements"])
    assert [run["sweep"]["values"] for run in document["measurements"]] == [[0], [0.1], [1]]
    before = (global_dir / "results/hpc_123.json").read_bytes()
    subprocess.run(["bash", str(ROOT / "hpc/slurm_broadcast.sh")], env=env, capture_output=True, text=True, check=True)
    assert (global_dir / "results/hpc_123.json").read_bytes() == before
    env.update(SLURM_ARRAY_JOB_ID="456", SLURM_JOB_ID="4560", SLURM_ARRAY_TASK_ID="0")
    subprocess.run(["bash", str(ROOT / "hpc/slurm_broadcast.sh")], env=env, capture_output=True, text=True, check=True)
    assert _source_text(load_hpc_job(global_dir / "results/hpc_456.json"), "hpc/snapshot_marker.py") == "generation = 'second'\n"
    assert {path.name for path in (global_dir / "results").iterdir()} == {"hpc_123.json", "hpc_456.json"}
    assert not (global_dir / "experiments").exists() and not (scratch / "experiments").exists()


def test_completed_hpc_task_skips_simulation_and_never_replaces_measurement(tmp_path, monkeypatch):
    arguments = ["--M", "1", "--N", "1", "--p-values", "0", "1", "--experiment-id", "abc", "--seed", "7"]
    path = prepare_hpc(ROOT, tmp_path / "results", "abc", arguments)
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "0")
    main([*arguments, "--execution-file", str(path)])
    before = path.read_bytes()
    monkeypatch.setattr("hpc.run_experiment.ExactBackend.run", lambda *a: pytest.fail("Existing task recomputed"))
    main([*arguments, "--execution-file", str(path)])
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="arguments differ"):
        prepare_hpc(ROOT, tmp_path / "results", "abc", [*arguments, "--use-qec"])
    with pytest.raises(ValueError, match="arguments differ"):
        prepare_hpc(ROOT, tmp_path / "results", "abc", arguments, array=False)
    restored = tmp_path / "source"
    extract_source(path, restored)
    assert (restored / "broadcasting/backend.py").read_bytes() == (ROOT / "broadcasting/backend.py").read_bytes()


@pytest.mark.skipif(shutil.which("rsync") is None, reason="Backup harness requires rsync")
def test_backup_preserves_existing_flat_record_and_copies_new_json(tmp_path):
    scratch, archive = tmp_path / "scratch", tmp_path / "global"
    for root in (scratch, archive):
        (root / "results").mkdir(parents=True)
    (scratch / "results/run_existing.json").write_text("different scratch bytes")
    (archive / "results/run_existing.json").write_text("original archived evidence")
    (scratch / "results/run_new.json").write_text("new evidence")
    env = dict(os.environ, BROADCAST_GLOBAL_DIR=str(archive), BROADCAST_SCRATCH_DIR=str(scratch))
    subprocess.run(["bash", str(ROOT / "hpc/backup_results.sh")], env=env, capture_output=True, text=True, check=True)
    assert (archive / "results/run_existing.json").read_text() == "original archived evidence"
    assert (archive / "results/run_new.json").read_text() == "new evidence"
    assert all(path.is_file() for path in (archive / "results").iterdir())


def test_fetch_merge_advances_partial_job_without_changing_completed_tasks(tmp_path, monkeypatch):
    from hpc.archive import merge_result_archives, _digest
    arguments = ["--M", "1", "--N", "1", "--p-values", "0", "1", "--experiment-id", "fetch", "--seed", "7"]
    remote, local = tmp_path / "remote", tmp_path / "local"
    path = prepare_hpc(ROOT, remote, "fetch", arguments)
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "0")
    main([*arguments, "--execution-file", str(path)])
    path.write_text(json.dumps(json.loads(path.read_text()), separators=(",", ":")))
    assert merge_result_archives(remote, local) == [local / path.name]
    assert (local / path.name).read_bytes() == path.read_bytes()
    first = load_hpc_job(local / path.name)["measurements"][0]
    partial_bytes = (local / path.name).read_bytes()
    # A changed existing task may never be published over the saved observation.
    incoming = json.loads(path.read_text())
    incoming["measurements"][0]["fidelities"][0][0] = 0.1
    path.write_text(json.dumps(incoming))
    with pytest.raises(ValueError, match="changed or removed an existing task"):
        merge_result_archives(remote, local)
    assert (local / path.name).read_bytes() == partial_bytes
    path.write_bytes(partial_bytes)
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "1")
    main([*arguments, "--execution-file", str(path)])
    path.write_text(json.dumps(json.loads(path.read_text()), separators=(",", ":")))
    assert merge_result_archives(remote, local) == [local / path.name]
    assert (local / path.name).read_bytes() == path.read_bytes()
    completed = load_hpc_job(local / path.name)
    assert completed["state"] == "completed" and len(list_runs(local)) == 2
    assert completed["measurements"][0] == first
    assert merge_result_archives(remote, local) == []
    before = (local / path.name).read_bytes()
    incoming = json.loads(path.read_text())
    incoming["prepared"]["source_snapshot"]["code_revision"] = "different"
    incoming["prepared_sha256"] = _digest(incoming["prepared"])
    path.write_text(json.dumps(incoming))
    with pytest.raises(ValueError, match="Conflicting frozen"):
        merge_result_archives(remote, local)
    assert (local / path.name).read_bytes() == before


def test_source_archive_includes_requirements(tmp_path):
    path = prepare_hpc(ROOT, tmp_path / "results", "pins", ["--M", "1", "--N", "1", "--p-values", "0"], array=False)
    document = load_hpc_job(path)
    assert _source_text(document, "requirements.txt") == (ROOT / "requirements.txt").read_text()


def test_fetch_imports_all_saved_result_types_with_exact_source_bytes(tmp_path, monkeypatch):
    from hpc.archive import merge_result_archives
    remote, local = tmp_path / "remote", tmp_path / "local"
    remote.mkdir()
    _run_tasks(remote, monkeypatch, points=(0,))
    runtime_source = next((ROOT / "results").glob("job_*.json"))
    for source in (runtime_source, ROOT / "results/run_seed_zero.json"):
        (remote / source.name).write_text(json.dumps(json.loads(source.read_text()), separators=(",", ":")))
    monkeypatch.setattr("broadcasting.experiments._service", lambda *a: pytest.fail("Fetch attempted network access"))
    monkeypatch.setattr("broadcasting.experiments._ordered_circuits", lambda *a: pytest.fail("Fetch replayed compiled circuits"))
    assert len(merge_result_archives(remote, local)) == 3
    for source in remote.iterdir():
        assert (local / source.name).read_bytes() == source.read_bytes()
    assert merge_result_archives(remote, local) == []
