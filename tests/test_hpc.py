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
    monkeypatch.setenv("SLURM_ARRAY_JOB_ID", "campaign")
    for index in range(len(points)):
        monkeypatch.setenv("SLURM_ARRAY_TASK_ID", str(index))
        main(["--M", "1", "--N", "1", "--thetas", "0.3", "--outcomes", "0",
              "--seed", "7", "--p-values", *map(str, points), "--output-dir", str(tmp_path)])
    return sorted(tmp_path.glob("run_*.json"))


def test_cli_grid_merge_requires_complete_matching_experiment(tmp_path, monkeypatch):
    paths = _run_tasks(tmp_path, monkeypatch)
    merged = _merge_group(paths)
    assert merged["sweep"]["values"] == [0, 0.1, 1]
    assert merged["metadata"]["sweep_complete"] is True
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
    first_source = scratch / "submissions/123/source/hpc/snapshot_marker.py"
    assert first_source.read_text() == "generation = 'first'\n"
    assert first_source.stat().st_mode & 0o222 == 0
    assert (global_dir / "results/submissions/123/source/hpc/snapshot_marker.py").read_text() == "generation = 'first'\n"
    paths = sorted((global_dir / "results/submissions/123").glob("run_*.json"))
    assert _merge_group(paths)["sweep"]["values"] == [0, 0.1, 1]
    env.update(SLURM_ARRAY_JOB_ID="456", SLURM_JOB_ID="4560", SLURM_ARRAY_TASK_ID="0")
    subprocess.run(["bash", str(root / "hpc/slurm_broadcast.sh")], env=env,
                   capture_output=True, text=True, check=True)
    assert (scratch / "submissions/456/source/hpc/snapshot_marker.py").read_text() == "generation = 'second'\n"
    assert first_source.read_text() == "generation = 'first'\n"
    # Restore only harness snapshots' write permission for pytest cleanup.
    for tree in (scratch / "submissions", global_dir / "results/submissions"):
        for path in tree.rglob("*"):
            if path.is_dir():
                path.chmod(path.stat().st_mode | 0o700)
