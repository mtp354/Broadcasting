"""Offline HPC checks: actual CLI tasks and isolated shell source snapshots."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from hpc.run_experiment import main
from scripts.merge_hpc_runs import _merge_group


def _run_tasks(tmp_path, monkeypatch, points=(0, 0.1, 1)):
    monkeypatch.setenv("SLURM_ARRAY_JOB_ID", "experiment")
    for index in range(len(points)):
        monkeypatch.setenv("SLURM_ARRAY_TASK_ID", str(index))
        main(["--M", "1", "--N", "1", "--thetas", "0.3", "--outcomes", "0",
              "--seed", "7", "--p-values", *map(str, points), "--output-dir", str(tmp_path)])
    return sorted(tmp_path.glob("run_*.json"))


def test_cli_grid_merge_requires_complete_matching_experiment(tmp_path, monkeypatch):
    paths = _run_tasks(tmp_path, monkeypatch)
    merged = _merge_group(paths)
    assert merged["sweep"] == {"axis": "p", "unit": "probability", "values": [0, 0.1, 1]}
    assert merged["schema_version"] == 2 and merged["experiment_kind"] == "broadcasting"
    from hashlib import sha256
    from broadcasting.results import validate_run_record
    validate_run_record(merged)
    assert merged["record_id"] not in {json.loads(path.read_text())["record_id"] for path in paths}
    sources = merged["metadata"]["execution"]["sources"]
    assert {source["sha256"] for source in sources} == {sha256(path.read_bytes()).hexdigest() for path in paths}
    assert merged["metadata"]["execution"]["sweep_complete"] is True
    with pytest.raises(ValueError, match="Incomplete"):
        _merge_group(paths[:-1])
    with pytest.raises(ValueError, match="Duplicate"):
        _merge_group([*paths, paths[0]])
    raw = json.loads(paths[0].read_text())
    raw["protocol"]["theta_samples"] = [[1.4]]
    replacement = tmp_path / "different_theta.json"
    replacement.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="different experiment"):
        _merge_group([replacement, *paths[1:]])


def test_cli_negative_array_index_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "-1")
    with pytest.raises(SystemExit):
        main(["--p-values", "0", "1", "--output-dir", str(tmp_path)])
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(shutil.which("rsync") is None or shutil.which("flock") is None,
                    reason="Shell snapshot harness requires rsync and flock")
def test_slurm_script_isolates_submissions_without_slurm_or_network(tmp_path):
    root = Path(__file__).resolve().parent.parent
    global_dir, scratch = tmp_path / "global", tmp_path / "scratch"
    global_dir.mkdir()
    scratch.mkdir()
    for folder in ("broadcasting", "hpc", "scripts"):
        shutil.copytree(root / folder, global_dir / folder,
                        ignore=shutil.ignore_patterns("__pycache__"))
    marker = global_dir / "hpc" / "snapshot_marker.py"
    marker.write_text("generation = 'first'\n")
    (scratch / ".venv").symlink_to(Path(sys.executable).parent.parent, target_is_directory=True)
    shell_init = tmp_path / "shell_init.sh"
    shell_init.write_text("module() { :; }\nexport -f module\n")
    env = dict(os.environ, BROADCAST_GLOBAL_DIR=str(global_dir), BROADCAST_SCRATCH_DIR=str(scratch),
               BASH_ENV=str(shell_init), M="1", N="1", MODE="exact", THETAS="0.3", OUTCOMES="0",
               SEED="7", P_LIST="0 0.1 1", SLURM_ARRAY_JOB_ID="123")
    for task in range(3):
        env.update(SLURM_ARRAY_TASK_ID=str(task), SLURM_JOB_ID=f"123{task}")
        subprocess.run(["bash", str(root / "hpc/slurm_broadcast.sh")], env=env,
                       capture_output=True, text=True, check=True)
        # A later global edit must never alter this submission's snapshot.
        marker.write_text("generation = 'second'\n")
    first_source = scratch / "experiments/submissions/123/source/hpc/snapshot_marker.py"
    assert first_source.read_text() == "generation = 'first'\n"
    assert first_source.stat().st_mode & 0o222 == 0
    assert (global_dir / "experiments/submissions/123/source/hpc/snapshot_marker.py").read_text() == "generation = 'first'\n"
    paths = sorted((global_dir / "results/records").glob("run_*.json"))
    assert _merge_group(paths)["sweep"]["values"] == [0, 0.1, 1]
    env.update(SLURM_ARRAY_JOB_ID="456", SLURM_JOB_ID="4560", SLURM_ARRAY_TASK_ID="0")
    subprocess.run(["bash", str(root / "hpc/slurm_broadcast.sh")], env=env,
                   capture_output=True, text=True, check=True)
    assert (scratch / "experiments/submissions/456/source/hpc/snapshot_marker.py").read_text() == "generation = 'second'\n"
    assert first_source.read_text() == "generation = 'first'\n"
    # Restore only harness snapshots' write permission for pytest cleanup.
    for tree in (scratch / "experiments/submissions", global_dir / "experiments/submissions"):
        for path in tree.rglob("*"):
            if path.is_dir():
                path.chmod(path.stat().st_mode | 0o700)


@pytest.mark.skipif(shutil.which("rsync") is None or shutil.which("flock") is None,
                    reason="Archive recovery harness requires rsync and flock")
def test_backup_recovers_failed_source_copy_and_preserves_results(tmp_path):
    root = Path(__file__).resolve().parent.parent
    scratch, archive = tmp_path / "scratch", tmp_path / "global"
    submission = scratch / "experiments/submissions/123"
    destination = archive / "experiments/submissions/123"
    scratch_results = scratch / "results/records"
    archive_results = archive / "results/records"
    for directory in (submission / "source", scratch_results, archive_results, destination):
        directory.mkdir(parents=True)
    (submission / "source/code.py").write_text("complete source")
    (scratch_results / "run_existing.json").write_text("different scratch bytes")
    (archive_results / "run_existing.json").write_text("original archived evidence")
    (scratch_results / "run_new.json").write_text("new evidence")
    env = dict(os.environ, BROADCAST_GLOBAL_DIR=str(archive),
               BROADCAST_SCRATCH_DIR=str(scratch))
    # Fail only the source copy, after writing part of its output.
    stub = tmp_path / "bin"
    stub.mkdir()
    rsync = stub / "rsync"
    rsync.write_text(
        "#!/bin/bash\n"
        'if [[ "${@: -2:1}" == */source/ ]]; then\n'
        '  touch "${@: -1}/partial"\n  exit 23\nfi\n'
        f'exec {shutil.which("rsync")} "$@"\n'
    )
    rsync.chmod(0o755)
    script = ["bash", str(root / "hpc/backup_results.sh")]
    failed = subprocess.run(script, env=dict(env, PATH=f"{stub}:{env['PATH']}"),
                            capture_output=True, text=True)
    assert failed.returncode == 23
    assert not (destination / "source").exists()
    assert not list(destination.glob(".source.*"))
    subprocess.run(script, env=env, capture_output=True, text=True, check=True)
    assert (destination / "source/code.py").read_text() == "complete source"
    assert (archive_results / "run_existing.json").read_text() == "original archived evidence"
    assert (archive_results / "run_new.json").read_text() == "new evidence"


def test_local_cli_and_merge_default_to_shared_records_without_replacing_sources(tmp_path, monkeypatch):
    from scripts.merge_hpc_runs import main as merge_main
    from broadcasting.results import load_run
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLURM_ARRAY_TASK_ID", raising=False)
    main(["--M", "1", "--N", "1", "--p-values", "0", "--seed", "7"])
    direct = list((tmp_path / "results/records").glob("run_*.json"))
    assert len(direct) == 1
    assert load_run(direct[0])["schema_version"] == 2
    task_paths = _run_tasks(tmp_path / "tasks", monkeypatch)
    before = {path: path.read_bytes() for path in task_paths}
    merge_main([str(path) for path in task_paths])
    outputs = list((tmp_path / "results/records").glob("run_*.json"))
    assert len(outputs) == 2
    merged_path = next(path for path in outputs if path != direct[0])
    merged = load_run(merged_path)
    assert merged["sweep"]["values"] == [0, 0.1, 1]
    assert all(path.read_bytes() == value for path, value in before.items())
