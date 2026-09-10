"""Execute actual notebook cells: offline defaults and explicit resumable actions."""
import json
from pathlib import Path

import pytest

from broadcasting import experiments
from broadcasting import convergence

ROOT = Path(__file__).resolve().parents[1]


def cells():
    notebook = json.loads((ROOT / "run_broadcast.ipynb").read_text())
    return {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"}


def execute(cell_id, namespace, *, enable=()):
    source = cells()[cell_id]
    for flag in enable:
        source = source.replace(f"{flag} = False", f"{flag} = True")
    exec(compile(source, f"run_broadcast.ipynb:{cell_id}", "exec"), namespace)


def configured_namespace(monkeypatch):
    monkeypatch.chdir(ROOT)
    namespace = {}
    execute("imports", namespace)
    for cell_id in ("hardware-settings", "scaling-config", "delay-config", "plan"):
        execute(cell_id, namespace)
    return namespace


def test_run_all_default_cells_show_existing_data_without_new_data_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline notebook attempted experiment data collection or account lookup")
    for name in ("_service", "prepare_experiment", "submit_experiment", "collect_experiment"):
        monkeypatch.setattr(experiments, name, forbidden)
    monkeypatch.setattr(convergence, "collect_convergence_repeats", forbidden)
    monkeypatch.setattr(experiments, "run_memory_reference", forbidden)
    monkeypatch.setattr(experiments, "build_memory_circuits", forbidden)
    monkeypatch.setattr("broadcasting.ExactBackend.run", forbidden)
    monkeypatch.setattr("broadcasting.SamplingBackend.run", forbidden)
    monkeypatch.setattr("broadcasting.results.save_run", forbidden)
    namespace = configured_namespace(monkeypatch)
    passed = {"imports", "hardware-settings", "scaling-config", "delay-config", "plan"}
    for cell_id in cells():
        if cell_id not in passed:
            execute(cell_id, namespace)
    assert namespace["IBM_PROFILE"] == "mprest1"
    assert namespace["plans"]["scaling"]["total_shots"] == 294912
    assert namespace["plans"]["delay"]["total_shots"] == 3630000
    assert namespace["memory_config"]["use_qec"] is True
    assert namespace["RESULTS_DIR"] == ROOT / "results"
    assert len(namespace["convergence_study"].sample_counts) == 10
    assert namespace["convergence_study"].sample_counts[-1] == 100000


def test_notebook_prepare_submit_collect_cells_use_inline_config_and_job_jsons(monkeypatch, tmp_path):
    namespace = configured_namespace(monkeypatch)
    calls = []
    namespace["experiments"] = {name: (namespace[f"{name}_config"], []) for name in ("scaling", "delay")}
    selected = {"scaling": [tmp_path / "job_scaling.json"], "delay": [tmp_path / "job_delay.json"]}
    def prepare(config, **kwargs):
        name = "scaling" if len(config["cases"]) > 1 else "delay"
        calls.append(("prepare", config, kwargs))
        return selected[name]
    namespace["prepare_experiment"] = prepare
    namespace["load_experiment"] = lambda path, expected_config=None: calls.append(("check", expected_config, path))
    namespace["submit_experiment"] = lambda paths: calls.append(("submit", paths)) or ["test-job"]
    namespace["collect_experiment"] = lambda paths: calls.append(("collect", paths)) or paths
    namespace["experiment_status"] = lambda paths: {"jobs": []}
    execute("prepare", namespace, enable=("PREPARE_SCALING", "PREPARE_DELAY"))
    execute("submit-scaling", namespace, enable=("SUBMIT_SCALING",))
    execute("submit-delay", namespace, enable=("SUBMIT_DELAY",))
    execute("collect", namespace, enable=("COLLECT_SCALING", "COLLECT_DELAY"))
    assert [row[0] for row in calls] == ["prepare", "prepare", "check", "submit", "check", "submit", "check", "collect", "check", "collect"]
    assert calls[0][1]["shots"] == 8192 and len(calls[0][1]["cases"]) == 12
    assert calls[1][1]["shots"] == 10000
    assert calls[0][2] == {"results_dir": namespace["RESULTS_DIR"]}
    assert calls[3][1] == selected["scaling"] and calls[5][1] == selected["delay"]


def test_notebook_convergence_uses_flat_results_and_embedded_study(monkeypatch, tmp_path):
    namespace = configured_namespace(monkeypatch)
    namespace["RESULTS_DIR"] = tmp_path / "results"
    namespace["convergence_study"] = convergence.load_convergence()
    namespace["load_convergence"] = lambda **kwargs: namespace["convergence_study"]
    calls = []
    namespace["collect_convergence_repeats"] = lambda study, **kwargs: calls.append((study, kwargs))
    execute("collect-convergence", namespace, enable=("RUN_CONVERGENCE",))
    assert len(calls) == 1
    study, options = calls[0]
    assert study.sample_counts == [50, 100, 200, 500, 1000, 2000, 5000, 10000, 50000, 100000]
    assert options == {"repeats": 2, "seeds": [3, 4], "results_dir": tmp_path / "results", "study_id": "repeats_02"}


def test_prepared_notebook_refuses_stale_config_before_submission(monkeypatch):
    namespace = configured_namespace(monkeypatch)
    namespace["experiments"]["scaling"] = (namespace["scaling_config"], [Path("results/job_prepared.json")])
    def mismatch(*args, **kwargs):
        raise ValueError("Notebook/config differs")
    namespace["load_experiment"] = mismatch
    namespace["submit_experiment"] = lambda *args: pytest.fail("Stale preparation submitted")
    with pytest.raises(ValueError, match="differs"):
        execute("submit-scaling", namespace, enable=("SUBMIT_SCALING",))


def test_execution_notebook_has_no_plotting_or_enabled_execution_switches():
    import ast
    for cell_id, source in cells().items():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [node.module] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
                assert not any(name and (name.startswith("matplotlib") or "plotting" in name) for name in names)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.startswith(("RUN_", "PREPARE_", "SUBMIT_", "COLLECT_", "BUILD_", "ATTACH_")):
                        assert isinstance(node.value, ast.Constant) and node.value.value is False, (cell_id, target.id)


def test_notebook_memory_actions_use_shared_job_json_lifecycle(monkeypatch, tmp_path):
    namespace = configured_namespace(monkeypatch)
    execute("memory-config", namespace)
    calls = []
    memory_file = tmp_path / "job_memory.json"
    namespace["memory_jobs"] = []
    def prepare(config, **kwargs):
        calls.append(("prepare", config, kwargs))
        return [memory_file]
    namespace["prepare_experiment"] = prepare
    namespace["load_experiment"] = lambda path, expected_config=None: calls.append(("check", expected_config, path))
    namespace["submit_experiment"] = lambda paths: calls.append(("submit", paths)) or ["job-1"]
    namespace["collect_experiment"] = lambda paths: calls.append(("collect", paths)) or paths
    execute("memory-hardware", namespace, enable=("PREPARE_MEMORY", "SUBMIT_MEMORY", "COLLECT_MEMORY"))
    assert [row[0] for row in calls] == ["prepare", "check", "submit", "check", "collect"]
    assert calls[0][1] == namespace["memory_config"]
    assert calls[0][2] == {"results_dir": namespace["RESULTS_DIR"]}
    assert calls[2][1] == calls[4][1] == [memory_file]
