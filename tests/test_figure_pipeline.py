"""Pinned inputs, safe defaults and optional notebook path execution."""
import ast
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from scripts import generate_figures as figures
from scripts import figure_sources
from broadcasting.analysis import delay_axis

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


def test_manuscript_notebook_preview_preserves_data_and_axis_ranges(monkeypatch):
    """Optional saved-campaign integration check, including log-axis autoscaling."""
    campaign_inputs = [
        ROOT / "campaigns" / campaign / "results" / f"repeat_{repeat:03d}_m1_n2.json"
        for campaign in ("delay_01", "delay_02") for repeat in range(3)
    ] + [
        ROOT / "campaigns/scaling_01/results" / f"repeat_{repeat:03d}_m{m}_n{n}.json"
        for repeat in range(3) for m in range(1, 4) for n in range(1, 5)
    ]
    if not all(path.is_file() for path in campaign_inputs):
        pytest.skip("The manuscript integration check needs the locally saved, gitignored campaigns.")

    notebook = json.loads((ROOT / "visualizations.ipynb").read_text())
    cell = next(cell for cell in notebook["cells"] if cell.get("id") == "manuscript-figures")
    tree = ast.parse("".join(cell["source"]))
    save_settings = [
        node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SAVE_MANUSCRIPT_FIGURES"
                for target in node.targets)
    ]
    assert len(save_settings) == 1
    save_settings[0].value = ast.Constant(value=False)
    ast.fix_missing_locations(tree)
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr("IPython.display.display", lambda *args, **kwargs: None)
    monkeypatch.setattr("broadcasting.plotting.save_figure",
                        lambda *args, **kwargs: pytest.fail("Preview attempted to save a figure"))
    namespace = {}
    try:
        exec(compile(tree, "visualizations.ipynb:manuscript-figures", "exec"), namespace)
        rendered = namespace["manuscript_figures"]
        assert set(rendered) == {1, 2, 4, 5, 6}
        memory_ax = rendered[2].axes[0]
        memory_cfg = namespace["FIGURE_2"]
        assert len(namespace["memory_runs"]) == len(memory_cfg["data_styles"]) == 4
        for run, style in zip(namespace["memory_runs"], memory_cfg["data_styles"]):
            lines = [line for line in memory_ax.lines if line.get_label() == style["label"]]
            assert len(lines) == 1
            scale, _unit = delay_axis(run)
            np.testing.assert_allclose(lines[0].get_xdata(), scale * np.asarray(run["tau_values"]))
            np.testing.assert_allclose(lines[0].get_ydata(), run["backend_fidelities"])
        memory_labels = [text.get_text() for text in memory_ax.get_legend().texts]
        assert all(not re.search(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b|\b\d{8}\b|historical|campaign",
                                 label, flags=re.IGNORECASE) for label in memory_labels)

        crossover_data = [line for line in rendered[4].axes[0].lines
                          if line.get_label().startswith(("Exact", "Sampled"))]
        assert [len(line.get_xdata()) for line in crossover_data] == [5, 50, 50]

        delay_axes = [ax for ax in rendered[5].axes if ax.get_visible()]
        assert len(delay_axes) == 2
        assert namespace["panel_backends"] == ["ibm_marrakesh", "ibm_kingston"]
        assert [len(group) for group in namespace["panel_traces"]] == [3, 3]
        expected_delay_sources = {
            backend: {ROOT / "campaigns" / campaign / "results" / f"repeat_{repeat:03d}_m1_n2.json"
                      for repeat in range(3)}
            for backend, campaign in [("ibm_marrakesh", "delay_01"), ("ibm_kingston", "delay_02")]
        }
        assert {Path(path).resolve() for path in namespace["FIGURE_5"]["sources"]} == set().union(
            *expected_delay_sources.values())
        for ax, backend, group in zip(delay_axes, namespace["panel_backends"], namespace["panel_traces"]):
            assert {Path(run["filepath"]).resolve() for run, _theta_index, _histograms in group} == expected_delay_sources[backend]
            assert all(run["backend"] == backend for run, _theta_index, _histograms in group)
            assert len(ax.lines) == 3 * len(group) + 1  # Two receivers, mean, one panel baseline.
            expected_bands = 2 * len(group) if namespace["FIGURE_5"]["show_intervals"] else 0
            assert len(ax.collections) == expected_bands
            assert [text.get_text() for text in ax.get_legend().texts] == ["Receiver 1", "Receiver 2", "Mean"]
            for run_index, (run, _theta_index, histograms) in enumerate(group):
                order = np.argsort(run["sweep"]["values"])
                expected = np.array([
                    [sum(weight for bits, weight in histograms[index].items() if bits[-receiver - 1] == "0")
                     / sum(histograms[index].values()) for receiver in range(run["N"])]
                    for index in order
                ])
                for receiver in range(2):
                    line = ax.lines[3 * run_index + receiver]
                    assert len(line.get_xdata()) == 121
                    np.testing.assert_allclose(line.get_ydata(), expected[:, receiver])
                np.testing.assert_allclose(ax.lines[3 * run_index + 2].get_ydata(), expected.mean(axis=1))

        assert len(namespace["scaling_points"]) == 55
        np.testing.assert_array_equal(rendered[6].axes[0].get_xticks(), [1, 2, 3, 4])

        convergence_ax = rendered[1].axes[0]
        convergence_cfg = namespace["FIGURE_1"]
        assert convergence_ax.get_xscale() == convergence_ax.get_yscale() == "log"
        assert len(convergence_ax.lines) == 16  # Two receivers + total for five seeds, plus reference.
        assert all(len(line.get_xdata()) == 10 for line in convergence_ax.lines)
        expected_errors = [np.asarray(namespace["study"].historical["errors_per_receiver"])]
        expected_errors += [np.asarray([point["errors_per_receiver"] for point in rep["points"]])
                            for rep in namespace["repetitions"]]
        for index, errors in enumerate(expected_errors):
            lines = convergence_ax.lines[3 * index:3 * index + 3]
            np.testing.assert_allclose(lines[0].get_ydata(), errors[:, 0])
            np.testing.assert_allclose(lines[1].get_ydata(), errors[:, 1])
            np.testing.assert_allclose(lines[2].get_ydata(), errors.sum(axis=1))
            component_styles = [*convergence_cfg["receiver_styles"], convergence_cfg["total_style"]]
            for line, component_style in zip(lines, component_styles):
                expected_style = {**convergence_cfg["line_style"], **component_style}
                for property_name in ("color", "marker", "linestyle", "alpha", "linewidth"):
                    assert getattr(line, f"get_{property_name}")() == expected_style[property_name]
        assert [text.get_text() for text in convergence_ax.get_legend().texts] == [
            convergence_cfg["reference_style"]["label"],
            *[style["label"] for style in component_styles],
        ]
        reference = convergence_ax.lines[-1]
        for property_name in ("color", "marker", "linestyle", "alpha", "linewidth"):
            assert getattr(reference, f"get_{property_name}")() == convergence_cfg["reference_style"][property_name]
        counts = np.asarray(namespace["study"].sample_counts)
        anchor = convergence_cfg["reference_anchor_index"]
        expected_reference = (convergence_cfg["reference_multiplier"] * expected_errors[0][anchor].sum()
                              * (counts / counts[anchor]) ** convergence_cfg["reference_exponent"])
        np.testing.assert_allclose(reference.get_ydata(), expected_reference)
        for limits, getter in [(convergence_ax.get_xlim(), "get_xdata"),
                               (convergence_ax.get_ylim(), "get_ydata")]:
            values = np.concatenate([np.asarray(getattr(line, getter)()) for line in convergence_ax.lines])
            assert 0 < limits[0] <= values.min() <= values.max() <= limits[1]
    finally:
        for fig in namespace.get("manuscript_figures", {}).values():
            plt.close(fig)
