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


def test_convergence_cli_delegates_original_grid_and_explicit_two_repeats(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(figures, "collect_convergence_repeats", lambda study, **kwargs: calls.append((study, kwargs)) or tmp_path)
    monkeypatch.setattr(figures, "generate_sampling_convergence", lambda *args, **kwargs: None)
    path = figures.collect_sampling_convergence([], collect=True, archive_dir=tmp_path)
    assert path == tmp_path
    study, settings = calls[0]
    assert settings["repeats"] == 2
    assert settings["sample_counts"] == study.sample_counts
    assert settings["sample_counts"][-1] == 100000
    assert study.config.seed == 0 and study.config.thetas == [0.0]


def test_default_figure_cli_never_collects(monkeypatch):
    monkeypatch.setattr("sys.argv", ["generate_figures.py", "--all"])
    monkeypatch.setattr(figures, "collect_sampling_convergence", lambda *a, **k: pytest.fail("Implicit collection"))
    calls = []
    names = ["sampling_convergence", "qec_memory", "qec_crossover", "delay_sweeps", "hardware_tau0"]
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
    assert manifest["figures"]["convergence"]["status"] == "restored_historical_summary_with_optional_independent_repeats"


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
