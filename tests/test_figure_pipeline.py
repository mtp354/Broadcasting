"""Preview the editable manuscript notebook against canonical saved measurements."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.text import Text
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _notebook():
    return json.loads((ROOT / "visualizations.ipynb").read_text())


def _code_cells():
    return {cell["id"]: "".join(cell["source"]) for cell in _notebook()["cells"]
            if cell["cell_type"] == "code"}


@pytest.fixture(scope="module")
def preview():
    cells = _code_cells()
    required_paths = {
        node.value for source in cells.values() for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.startswith("results/") and node.value.endswith(".json")
    }
    if any(not (ROOT / path).is_file() for path in required_paths):
        pytest.skip("Manuscript integration requires the selected local measurement records.")

    def forbidden(*args, **kwargs):
        pytest.fail("Notebook preview attempted export, a build, or experiment execution")

    namespace = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(ROOT)
        patch.setattr("IPython.display.display", lambda *args, **kwargs: None)
        patch.setattr(Figure, "savefig", forbidden)
        patch.setattr("subprocess.run", forbidden)
        patch.setattr("broadcasting.experiments._service", forbidden)
        patch.setattr("broadcasting.ExactBackend.run", forbidden)
        patch.setattr("broadcasting.SamplingBackend.run", forbidden)
        patch.setattr("broadcasting.convergence.collect_convergence_repeats", forbidden)
        try:
            for cell_id, source in cells.items():
                tree = ast.parse(source)
                if cell_id == "visualization-settings":
                    for node in tree.body:
                        if isinstance(node, ast.Assign) and any(
                                isinstance(target, ast.Name) and target.id in
                                {"SAVE_MANUSCRIPT_FIGURES", "BUILD_MANUSCRIPT"} for target in node.targets):
                            node.value = ast.Constant(value=False)
                    ast.fix_missing_locations(tree)
                exec(compile(tree, f"visualizations.ipynb:{cell_id}", "exec"), namespace)
            yield namespace
        finally:
            for figure in namespace.get("manuscript_figures", {}).values():
                plt.close(figure)


@pytest.mark.parametrize("name", ["run_broadcast.ipynb", "visualizations.ipynb"])
def test_notebook_code_compiles(name):
    notebook = json.loads((ROOT / name).read_text())
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"{name}:{cell['id']}", "exec")


def test_six_editable_figure_cells_share_preview_export_and_source_evidence(preview):
    figures = preview["manuscript_figures"]
    assert set(figures) == set(range(1, 7))
    assert preview["SAVE_MANUSCRIPT_FIGURES"] is preview["BUILD_MANUSCRIPT"] is False
    assert set(preview["figure_settings"]) == set(figures)
    cells = _code_cells()
    for number in figures:
        source = cells[f"figure-{number}"]
        assignments = {target.id for node in ast.parse(source).body if isinstance(node, ast.Assign)
                       for target in node.targets if isinstance(target, ast.Name)}
        assert f"FIGURE_{number}" in assignments
        assert preview[f"FIGURE_{number}"]["filename"].endswith(".png")
        assert preview["manuscript_sources"][number]
        for source_record in preview["manuscript_sources"][number]:
            path = ROOT / source_record["path"]
            assert source_record["sha256"] == sha256(path.read_bytes()).hexdigest()
    for source in cells.values():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "broadcasting.plotting"
            if isinstance(node, ast.Import):
                assert all(alias.name != "broadcasting.plotting" for alias in node.names)


def test_legends_and_inset_have_smaller_readable_text(preview):
    size, legend_size = preview["FONT_SIZE"], preview["LEGEND_FONT_SIZE"]
    assert legend_size < size
    for number, figure in preview["manuscript_figures"].items():
        figure.canvas.draw()
        for ax in figure.axes:
            legend = ax.get_legend()
            if legend:
                assert all(text.get_fontsize() < size for text in legend.get_texts())
            if ax.get_xlabel():
                assert ax.xaxis.label.get_fontsize() == size
            if ax.get_ylabel():
                assert ax.yaxis.label.get_fontsize() == size
    inset = preview["manuscript_figures"][4].axes[0].child_axes[0]
    assert len(inset.get_xticks()) >= 5 and len(inset.get_yticks()) >= 5
    assert all(text.get_fontsize() == preview["INSET_FONT_SIZE"]
               for text in inset.get_xticklabels() + inset.get_yticklabels())
    legend = preview["manuscript_figures"][6].axes[0].get_legend()
    bounds = [text.get_window_extent() for text in legend.get_texts()]
    centers = [(box.y0 + box.y1) / 2 for box in bounds]
    assert max(centers) - min(centers) < 3
    axes_bounds = preview["manuscript_figures"][6].axes[0].get_window_extent()
    assert legend.get_window_extent().x0 >= axes_bounds.x0
    assert legend.get_window_extent().x1 <= axes_bounds.x1


def test_circuit_is_one_continuous_row_with_all_operations(preview):
    figure = preview["manuscript_figures"][3]
    assert len(figure.axes) == 1
    original = preview["figure_3_source"]
    drawing = preview["figure_3_drawing"]
    assert len(drawing.data) == len(original.data)
    assert sum(item.operation.name == "if_else" for item in drawing.data) == 3
    # Only display labels and the initializer's presentation wrapper may differ.
    for actual, expected in zip(drawing.data, original.data):
        assert actual.qubits == expected.qubits and actual.clbits == expected.clbits
        if expected.operation.name == "initialize":
            assert actual.operation.definition.data[0].operation == expected.operation
        elif expected.operation.name == "unitary":
            np.testing.assert_array_equal(actual.operation.to_matrix(), expected.operation.to_matrix())
        else:
            assert actual.operation == expected.operation
    assert figure.get_figwidth() > 3 * figure.get_figheight()


def _receiver_fidelities(histogram, receivers):
    total = sum(histogram.values())
    return [sum(count for bits, count in histogram.items() if bits[-receiver - 1] == "0") / total
            for receiver in range(receivers)]


def test_delay_panels_preserve_six_complete_sweeps_and_physical_delay(preview):
    axes = preview["manuscript_figures"][5].axes
    groups = preview["panel_traces"]
    assert len(axes) == 2 and [len(group) for group in groups] == [3, 3]
    assert preview["panel_backends"] == ["ibm_marrakesh", "ibm_kingston"]
    expected_records = {
        "ibm_marrakesh": {"f7068f1a0f6e30f1f59c7b89", "ab308009275a9870be5da092", "e4f7225c3728c2e2636e77e8"},
        "ibm_kingston": {"167fb3eb6f12f6f134c53899", "6db69732653e94b46f5b1947", "853078b05ee112186a10942a"},
    }
    for ax, backend, group in zip(axes, preview["panel_backends"], groups):
        assert {run["record_id"] for run, _, _ in group} == expected_records[backend]
        assert len(ax.lines) == 10  # Three receivers/mean curves per run and the reference level.
        assert [text.get_text() for text in ax.get_legend().texts] == ["Receiver 1", "Receiver 2", "Mean"]
        for run_index, (run, theta_index, histograms) in enumerate(group):
            assert run["backend"] == backend and run["schema_version"] == 2
            order = np.argsort(run["sweep"]["values"])
            assert len(order) == 121
            recorded_dt = run["metadata"]["dt"]
            assert recorded_dt > 0
            physical_tau = np.asarray(run["sweep"]["values"])[order] * recorded_dt * 1e6
            expected = np.asarray([_receiver_fidelities(histograms[index], 2) for index in order])
            for receiver in range(2):
                line = ax.lines[3 * run_index + receiver]
                np.testing.assert_allclose(line.get_xdata(), physical_tau)
                np.testing.assert_allclose(line.get_ydata(), expected[:, receiver])
            mean_line = ax.lines[3 * run_index + 2]
            np.testing.assert_allclose(mean_line.get_xdata(), physical_tau)
            np.testing.assert_allclose(mean_line.get_ydata(), expected.mean(axis=1))
    assert axes[0].get_ylabel() and not axes[1].get_ylabel()


def test_memory_and_crossover_preserve_native_measurements_and_reference(preview):
    ax = preview["manuscript_figures"][2].axes[0]
    runs, cfg = preview["memory_runs"], preview["FIGURE_2"]
    assert [(run["use_qec"], run["optimization_level"]) for run in runs] == [
        (True, 3), (True, 0), (False, 3), (False, 0)]
    for run, style in zip(runs, cfg["data_styles"]):
        assert run["schema_version"] == 2 and run["experiment_kind"] == "memory"
        line, = [line for line in ax.lines if line.get_label() == style["label"]]
        physical_tau = np.asarray(run["sweep"]["values"]) * run["metadata"]["dt"] * 1e6
        np.testing.assert_allclose(line.get_xdata(), physical_tau)
        np.testing.assert_allclose(line.get_ydata(), np.asarray(run["fidelities"])[:, 0])
    reference, = [line for line in ax.lines if line.get_label() == cfg["ideal_style"]["label"]]
    np.testing.assert_allclose(reference.get_xdata(),
                               np.asarray(runs[0]["sweep"]["values"]) * runs[0]["metadata"]["dt"] * 1e6)
    np.testing.assert_allclose(reference.get_ydata(), np.asarray(runs[0]["reference_fidelities"]["ideal"])[:, 0])
    assert all(not re.search(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b|historical|campaign",
                             text.get_text(), flags=re.IGNORECASE) for text in ax.get_legend().texts)

    crossover = preview["manuscript_figures"][4].axes[0]
    curves = [line for line in crossover.lines if line.get_label().startswith(("Exact", "Sampled"))]
    assert [len(line.get_xdata()) for line in curves] == [5, 50, 50]
    for line, run in zip(curves, preview["crossover_runs"]):
        np.testing.assert_array_equal(line.get_xdata(), run["sweep"]["values"])
        np.testing.assert_allclose(line.get_ydata(), np.asarray(run["fidelities"]).mean(axis=1))


def test_convergence_retains_independent_receiver_errors_and_component_totals(preview):
    ax, cfg = preview["manuscript_figures"][1].axes[0], preview["FIGURE_1"]
    assert ax.get_xscale() == ax.get_yscale() == "log"
    assert len(ax.lines) == 16
    series = [(preview["study"].sample_counts, preview["study"].seed_zero["errors_per_receiver"])]
    series.extend(([point["n_samples"] for point in repetition["points"]],
                   [point["errors_per_receiver"] for point in repetition["points"]])
                  for repetition in preview["repetitions"])
    assert len(series) == 5
    component_styles = [*cfg["receiver_styles"], cfg["total_style"]]
    for index, (samples, values) in enumerate(series):
        errors = np.asarray(values)
        for line, expected, component in zip(ax.lines[3 * index:3 * index + 3],
                                              [errors[:, 0], errors[:, 1], errors.sum(axis=1)], component_styles):
            np.testing.assert_array_equal(line.get_xdata(), samples)
            np.testing.assert_allclose(line.get_ydata(), expected)
            style = {**cfg["line_style"], **component}
            assert line.get_color() == style["color"]
            assert line.get_alpha() == style["alpha"]
    reference = ax.lines[-1]
    counts = np.asarray(series[0][0])
    anchor = cfg["reference_anchor_index"]
    expected_reference = (cfg["reference_multiplier"] * np.asarray(series[0][1])[anchor].sum()
                          * (counts / counts[anchor]) ** cfg["reference_exponent"])
    np.testing.assert_allclose(reference.get_ydata(), expected_reference)
    assert [text.get_text() for text in ax.get_legend().texts] == [
        cfg["reference_style"]["label"], *[style["label"] for style in component_styles]]
    for bounds, getter in [(ax.get_xlim(), "get_xdata"), (ax.get_ylim(), "get_ydata")]:
        values = np.concatenate([np.asarray(getattr(line, getter)()) for line in ax.lines])
        assert 0 < bounds[0] <= values.min() <= values.max() <= bounds[1]


def test_scaling_retains_all_eligible_observations_and_receiver_ranges(preview):
    points, ax = preview["scaling_points"], preview["manuscript_figures"][6].axes[0]
    assert len(points) == len(ax.containers) == 58
    records = {run["record_id"]: run for run in preview["records"]}
    assert len({(point["record_id"], point["theta_index"]) for point in points}) == 58
    for point, container in zip(points, ax.containers):
        run = records[point["record_id"]]
        assert run["experiment_kind"] == "broadcasting" and run["experiment_type"] == "hardware"
        assert run["optimization_level"] == 3 and run["use_qec"] is False
        zero, = np.flatnonzero(np.asarray(run["sweep"]["values"]) == 0)
        values = _receiver_fidelities(run["counts"][point["theta_index"]][zero], run["N"])
        assert point["mean"] == pytest.approx(np.mean(values))
        assert point["minimum"] == pytest.approx(min(values), rel=0, abs=1e-12)
        assert point["maximum"] == pytest.approx(max(values), rel=0, abs=1e-12)
        line, _caps, bars = container.lines
        np.testing.assert_allclose(np.asarray(line.get_ydata(), dtype=float), [np.mean(values)])
        np.testing.assert_allclose(bars[0].get_segments()[0][:, 1], [min(values), max(values)])
        assert abs(float(line.get_xdata()[0]) - run["N"]) <= preview["FIGURE_6"]["horizontal_spread"] / 2 + 1e-12
    np.testing.assert_array_equal(ax.get_xticks(), [1, 2, 3, 4])
    assert {"Fez", "Kingston", "Marrakesh"} <= {text.get_text() for text in ax.get_legend().texts}
