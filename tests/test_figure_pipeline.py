"""Pinned inputs, safe defaults and optional notebook path execution."""
import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from scripts import generate_figures as figures
from scripts import figure_sources

ROOT = Path(__file__).resolve().parent.parent


def test_convergence_refuses_implicit_collection():
    with pytest.raises(ValueError, match="explicit collection"):
        figures.collect_sampling_convergence([])


def test_convergence_sets_effective_seed_and_count_and_archives_measurements(monkeypatch, tmp_path):
    observed = []

    class Exact:
        def run(self, config):
            return SimpleNamespace(fidelities=np.full((len(config.p_list), 2), 0.5))

    class Sampled:
        def run(self, config):
            observed.append((config.seed, config.n_samples))
            assert config.seed is not None
            assert config.n_samples is not None
            return SimpleNamespace(
                fidelities=np.full((len(config.p_list), 2), 0.5 + (config.seed + 1) / config.n_samples),
                metadata={"seed": config.seed, "n_samples": config.n_samples, "software": {"test": "fixture"}},
            )

    monkeypatch.setattr(figures, "ExactBackend", Exact)
    monkeypatch.setattr(figures, "SamplingBackend", Sampled)
    path = figures.collect_sampling_convergence([], collect=True, quick=True, archive_dir=tmp_path)
    archive = json.loads(path.read_text())
    assert observed == [(seed, n) for seed in [0, 1, 2] for n in [50, 100, 200, 500, 1000]]
    assert len(archive["measurements"]) == len(observed)
    for measurement, (seed, count) in zip(archive["measurements"], observed):
        assert measurement["seed"] == seed
        assert measurement["n_samples"] == count
        assert measurement["execution_metadata"]["software"] == {"test": "fixture"}
        assert measurement["error_area"] == pytest.approx(2 * (seed + 1) / count)


def test_default_figure_cli_never_collects(monkeypatch):
    monkeypatch.setattr("sys.argv", ["generate_figures.py", "--all"])
    monkeypatch.setattr(figures, "collect_sampling_convergence", lambda *a, **k: pytest.fail("Implicit collection"))
    calls = []
    names = ["qec_memory", "qec_crossover", "delay_sweeps", "hardware_tau0"]
    for name in names:
        monkeypatch.setattr(figures, f"generate_{name}", lambda *a, n=name, **k: calls.append(n))
    figures.main()
    assert calls == names


def test_manifest_sources_are_intact_and_qec_attributions_are_explicit():
    manifest = figure_sources.source_manifest()
    for source in manifest["runs"]:
        figure_sources.load_source(source, manifest=manifest)
    memory = figure_sources.figure_runs("qec_memory")
    assert [r["use_qec"] for r in memory] == [True, True, False, False]
    assert all(r["historical_provenance"]["dt"]["evidence"] for r in memory)
    assert manifest["figures"]["qec_memory"]["manuscript_output"] == "qec513_delay_sweep_idle"
    assert manifest["figures"]["convergence"]["status"] == "withdrawn_pending_new_collection"


def test_source_overlay_fills_null_but_rejects_conflicting_record(monkeypatch, tmp_path):
    from hashlib import sha256
    path = tmp_path / "results/qec513/test.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"use_qec": None, "metadata": {"dt": None}}))
    spec = {"sha256": sha256(path.read_bytes()).hexdigest(), "historical_overrides": {
        "use_qec": {"value": False, "evidence": "test fixture"}, "dt": {"value": 4e-9, "evidence": "test fixture"}}}
    manifest = {"runs": {"results/qec513/test.json": spec}}
    monkeypatch.setattr(figure_sources, "ROOT", tmp_path)
    run = figure_sources.load_source("results/qec513/test.json", manifest=manifest)
    assert run["use_qec"] is False
    assert run["metadata"]["dt"] == 4e-9
    assert json.loads(path.read_text())["use_qec"] is None
    path.write_text(json.dumps({"use_qec": True}))
    spec["sha256"] = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="conflicts"):
        figure_sources.load_source("results/qec513/test.json", manifest=manifest)


def test_crossover_uses_each_native_grid_and_returns_inset():
    fig = figures.generate_qec_crossover([])
    ax = fig.axes[0]
    assert len(ax.child_axes) == 1
    # The historical bare grid has five points, encoded curves have fifty.
    assert [len(line.get_xdata()) for line in ax.lines[2:5]] == [5, 50, 50]
    plt.close(fig)


def _notebook_cell(name, index):
    notebook = json.loads((ROOT / name).read_text())
    return "".join(line for line in notebook["cells"][index]["source"] if not line.startswith("%"))


@pytest.mark.parametrize("name", ["run_broadcast.ipynb", "visualizations.ipynb", "qec_testing.ipynb"])
def test_all_notebook_code_cells_compile(name):
    notebook = json.loads((ROOT / name).read_text())
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile(_notebook_cell(name, index), f"{name}:{index}", "exec")


def test_optional_periodicity_cell_loads_existing_flat_schema(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(plt, "show", lambda: None)
    namespace = {"SAVE_FIGURES": False}
    exec(_notebook_cell("run_broadcast.ipynb", 1), namespace)
    code = _notebook_cell("run_broadcast.ipynb", 13).replace("RUN_PERIODICITY_ANALYSIS = False", "RUN_PERIODICITY_ANALYSIS = True")
    exec(code, namespace)
    assert namespace["target_run"]["N"] == 2
    assert namespace["target_run"]["sweep"]["axis"] == "tau"
    assert namespace["unit"] == "us"
    plt.close("all")


def test_optional_convergence_notebook_delegates_to_explicit_collection(monkeypatch):
    calls = []
    monkeypatch.setattr(figures, "collect_sampling_convergence", lambda *args, **kwargs: calls.append(kwargs))
    code = _notebook_cell("run_broadcast.ipynb", 11).replace("RUN_CONVERGENCE = False", "RUN_CONVERGENCE = True")
    exec(code, {"SAVE_FIGURES": False})
    assert calls == [{"quick": False, "collect": True}]


def test_qec_saved_comparison_and_disabled_hardware_cells_execute(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(plt, "show", lambda: None)
    namespace = {"RUN_HARDWARE": False, "SAVE_FIGURE": False, "QEC_RESULTS_DIR": Path("results/qec513")}
    exec(_notebook_cell("qec_testing.ipynb", 1), namespace)
    exec(_notebook_cell("qec_testing.ipynb", 9), namespace)
    assert namespace["qec_outfile"] is None
    exec(_notebook_cell("qec_testing.ipynb", 13), namespace)
    assert len(namespace["saved"]) == 5
    plt.close("all")
