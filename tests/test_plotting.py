"""Tests for plotting helpers."""

import json

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from broadcasting.plotting import (
    autocorrelation_from_run,
    clear_titles,
    periodogram_from_run,
    plot_fidelity_vs_noise,
    hardware_scaling_points,
    plot_hardware_scaling,
    plot_delay_repeats,
    plot_periodicity_comparison,
    plot_run_sweep,
    save_figure,
)
from broadcasting.protocol import BroadcastResult, ProtocolConfig
from broadcasting.results import list_runs, load_run, save_run


def test_clear_titles_removes_axes_and_suptitle():
    fig, ax = plt.subplots()
    fig.suptitle("Figure title")
    ax.set_title("Axes title")

    clear_titles(fig)

    assert getattr(fig, "_suptitle", None) is None
    assert ax.get_title() == ""
    plt.close(fig)


def test_save_figure_strips_titles(tmp_path):
    fig, ax = plt.subplots()
    ax.set_title("Do not export")

    out = save_figure(fig, tmp_path / "figure.png")

    assert out.exists()
    assert ax.get_title() == ""
    plt.close(fig)


@pytest.mark.parametrize("filename,kwargs", [("figure.pdf", {}), ("figure.png", {"format": "pdf"}),
                                            ("figure.svg", {})])
def test_save_figure_rejects_non_png_before_writing(tmp_path, filename, kwargs):
    fig, _ = plt.subplots()
    with pytest.raises(ValueError, match="PNG only"):
        save_figure(fig, tmp_path / filename, **kwargs)
    assert not list(tmp_path.iterdir())
    plt.close(fig)


def _hardware_run(*, senders=1, receivers=2, opt=3, job="job-1", phases=None, dt=2e-9):
    phases = phases or [[0.2] * senders]
    counts = {"0" * receivers: 70, "1" * receivers: 10}
    if receivers > 1:
        counts["1" + "0" * (receivers - 1)] = 20
    else:
        counts["0"] += 20
    return {"experiment_type": "hardware", "M": senders, "N": receivers,
            "optimization_level": opt, "job_id": job, "backend": "ibm_test",
            "shots": 100, "timestamp": "2026-09-08T12:00:00", "filename": f"run_{job}.json",
            "theta_samples": phases, "sweep": {"axis": "tau", "values": [0, 100]},
            "counts": [[counts, counts] for _ in phases], "metadata": {"dt": dt}}


def test_scaling_coordinates_opt3_filter_sender_colors_and_receiver_ranges():
    runs = [_hardware_run(opt=0, job="excluded"),
            _hardware_run(job="m1n2"),
            _hardware_run(senders=2, receivers=3, job="m2n3"),
            _hardware_run(receivers=3, job="m1n3")]
    fig = plot_hardware_scaling(runs)
    points, ax = fig.broadcasting_points, fig.axes[0]
    assert len(points) == 3
    assert {point["job_id"] for point in points} == {"m1n2", "m1n3", "m2n3"}
    assert ax.get_xlabel() == "Number of receivers, N"
    assert "fidelity" in ax.get_ylabel()
    assert ax.get_xticks().tolist() == [2, 3]
    colors = {}
    for point, container in zip(points, ax.containers):
        line, _, bars = container.lines
        assert line.get_xdata()[0] == pytest.approx(point["x"])
        assert abs(point["x"] - point["N"]) <= 0.22 + 1e-12
        assert line.get_ydata()[0] == pytest.approx(point["mean"])
        assert point["minimum"] == pytest.approx(0.7)
        assert point["maximum"] == pytest.approx(0.9)
        segment = bars[0].get_segments()[0]
        assert segment[:, 1].tolist() == pytest.approx([0.7, 0.9])
        if point["M"] in colors:
            assert line.get_color() == colors[point["M"]]
        colors[point["M"]] = line.get_color()
    assert colors[1] != colors[2]
    plt.close(fig)


def test_scaling_keeps_phase_samples_campaign_cases_and_repeats_separate():
    runs = []
    for repeat in range(2):
        for case in ["all", "receiver0"]:
            run = _hardware_run(job=f"shared-{repeat}", phases=[[0.2], [1.5]])
            run["metadata"]["campaign"] = {"run_id": "campaign", "repeat_index": repeat, "case_id": case}
            runs.append(run)
    points = hardware_scaling_points([*runs, runs[0]])
    assert len(points) == 8
    assert len({point["x"] for point in points}) == 8
    assert {point["thetas"][0] for point in points} == {0.2, 1.5}
    assert points == hardware_scaling_points(list(reversed(runs)))


def test_scaling_rejects_dataset_without_opt3_zero_delay():
    with pytest.raises(ValueError, match="No opt3"):
        plot_hardware_scaling([_hardware_run(opt=0)])


def test_scaling_equal_receiver_fidelities_tolerates_mean_roundoff():
    run = _hardware_run(receivers=3)
    run["counts"] = [[{"000": 1, "111": 9}, {"000": 1, "111": 9}]]
    fig = plot_hardware_scaling([run])
    point = fig.broadcasting_points[0]
    assert point["mean"] == pytest.approx(0.1)
    assert point["minimum"] == point["maximum"] == 0.1
    segment = fig.axes[0].containers[0].lines[2][0].get_segments()[0]
    assert segment[:, 1].tolist() == pytest.approx([0.1, 0.1])
    plt.close(fig)


def test_delay_repeats_preserve_angles_repeat_identity_and_time_units():
    first = _hardware_run(phases=[[0.2], [1.7]])
    first["metadata"]["campaign"] = {"run_id": "campaign", "repeat_index": 2,
                                     "case_id": "receiver0", "receiver_delay_factors": [1, 0]}
    second = _hardware_run(job="unknown-dt", dt=None)
    fig = plot_delay_repeats([first, second])
    visible = [ax for ax in fig.axes if ax.get_visible()]
    assert len(visible) == 3
    for ax in visible[:2]:
        assert ax.containers[0].lines[0].get_xdata().tolist() == pytest.approx([0, 0.2])
        assert ax.get_xlabel() == "Idle delay (us)"
        assert "repeat 2" in ax.texts[0].get_text()
        assert "Receiver delay factors: [1, 0]" in ax.texts[0].get_text()
    assert "[0.200]" in visible[0].texts[0].get_text()
    assert "[1.700]" in visible[1].texts[0].get_text()
    assert visible[2].get_xlabel() == "Idle delay (dt)"
    assert visible[2].containers[0].lines[0].get_xdata().tolist() == [0, 100]
    plt.close(fig)


def test_list_runs_loads_nested_campaign_results_excluding_receipts_and_analysis(tmp_path):
    config = ProtocolConfig(M=1, N=1, thetas=[0.2], use_qec=False)
    result = BroadcastResult(fidelities=[[0.9]], metadata={"mode": "exact", "p_list": [0]})
    save_run(result, config, filepath=tmp_path / "run_old.json")
    save_run(result, config, filepath=tmp_path / "campaign/results/repeat_000_m1_n1.json")
    for relative in ["campaign/receipts/repeat_000.json", "campaign/attempts/repeat_000.json",
                     "campaign/prepared.json", "analysis/summary.json", "legacy/run_old.json"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    assert {run["filename"] for run in list_runs(tmp_path)} == {"run_old.json", "repeat_000_m1_n1.json"}


def test_plot_fidelity_vs_noise_has_no_title_by_default():
    fig = plot_fidelity_vs_noise(
        np.array([0.0, 0.5]),
        {"Receiver 0": np.array([1.0, 0.7])},
        show=False,
    )

    assert fig.axes[0].get_title() == ""
    plt.close(fig)


def test_plot_run_sweep_has_no_title_by_default():
    run = {
        "N": 2,
        "sweep": {"axis": "p", "values": [0.0, 0.5]},
        "fidelities": [[1.0, 1.0], [0.7, 0.75]],
    }

    fig = plot_run_sweep(run, show=False)

    assert fig.axes[0].get_title() == ""
    plt.close(fig)


def _tau_run(fidelities):
    tau = np.linspace(0, 6000, len(fidelities)).tolist()
    return {
        "N": 2,
        "sweep": {"axis": "tau", "values": tau},
        "fidelities": fidelities,
    }


def test_autocorrelation_from_run_normalized_at_zero_lag():
    n = 40
    tau = np.linspace(0, 6000, n)
    trace = 0.8 + 0.1 * np.cos(2 * np.pi * tau / 1000)
    run = _tau_run([[v, v] for v in trace])

    lags, ac = autocorrelation_from_run(run)

    assert lags[0] == 0.0
    assert ac[0] == pytest.approx(1.0)
    assert len(lags) == len(ac) == n


def test_periodogram_from_run_detects_dominant_frequency():
    n = 60
    tau = np.linspace(0, 6000, n)
    period = 1000.0
    trace = 0.8 + 0.1 * np.cos(2 * np.pi * tau / period)
    run = _tau_run([[v, v] for v in trace])

    freqs, power = periodogram_from_run(run)
    peak_freq = freqs[np.argmax(power)]

    assert peak_freq == pytest.approx(1.0 / period, rel=0.15)


def test_periodogram_from_run_requires_tau_axis():
    run = {"N": 2, "sweep": {"axis": "p", "values": [0.0, 0.5]}, "fidelities": [[1.0, 1.0], [0.7, 0.75]]}

    with pytest.raises(ValueError):
        periodogram_from_run(run)


def test_plot_periodicity_comparison_requires_matching_lengths():
    run = _tau_run([[0.8, 0.8], [0.7, 0.7]])

    with pytest.raises(ValueError):
        plot_periodicity_comparison([run], labels=["run A", "run B"])


def test_plot_periodicity_comparison_returns_two_panel_figure():
    n = 30
    tau = np.linspace(0, 6000, n)
    off = 0.8 + 0.1 * np.cos(2 * np.pi * tau / 1200)
    on = 0.85 + 0.05 * np.cos(2 * np.pi * tau / 1200)
    runs = [_tau_run([[v, v] for v in off]), _tau_run([[v, v] for v in on])]

    fig = plot_periodicity_comparison(runs, labels=["run A", "run B"], show=False)

    assert len(fig.axes) == 2
    plt.close(fig)


def test_save_run_preserves_hardware_tau_sweep(tmp_path):
    config = ProtocolConfig(M=1, N=2, thetas=[0.1], use_qec=False)
    result = BroadcastResult(
        fidelities=[[0.9, 0.8], [0.7, 0.6]],
        metadata={
            "mode": "hardware (fake_backend)",
            "backend": "fake_backend",
            "optimization_level": 2,
            "shots": 100,
            "job_id": "job-1",
            "sweep_axis": "tau",
            "sweep_values": [0, 100],
            "theta_samples": [[0.1]],
            "counts": [[{"00": 80, "11": 20}, {"00": 60, "11": 40}]],
        },
    )

    out = save_run(result, config, results_dir=tmp_path)
    loaded = load_run(out)

    assert loaded["experiment_type"] == "hardware"
    assert loaded["sweep"] == {"axis": "tau", "values": [0, 100]}
    assert loaded["fidelities"] == [[0.9, 0.8], [0.7, 0.6]]
    assert loaded["optimization_level"] == 2

    with open(out) as f:
        raw = json.load(f)
    assert raw["protocol"]["theta_samples"] == [[0.1]]


def test_periodicity_scaled_frequency_and_density_preserve_integral():
    tau = np.arange(0, 2000, 10)
    trace = 0.8 + 0.1 * np.cos(2 * np.pi * tau / 200)
    run = {"N": 1, "sweep": {"axis": "tau", "values": tau.tolist()},
           "fidelities": trace[:, None].tolist()}
    frequencies, density = periodogram_from_run(run)
    fig = plot_periodicity_comparison([run], ["synthetic"], tau_scale=0.004,
                                     tau_label="Idle delay (us)", show=False)
    plotted_frequency, plotted_density = fig.axes[1].lines[0].get_data()
    peak = int(np.argmax(plotted_density))
    assert plotted_frequency[peak] == pytest.approx(1.25)
    assert np.trapezoid(plotted_density, plotted_frequency) == pytest.approx(np.trapezoid(density, frequencies))
    assert "fidelity² us" in fig.axes[1].get_ylabel()
    assert fig.axes[0].get_xlabel() == "Lag (us)"
    plt.close(fig)


@pytest.mark.parametrize("values", [[0, 0, 1], [0, 1, 3], [0, 1, float("nan")]])
def test_periodicity_rejects_duplicate_irregular_or_nonfinite_grid(values):
    run = {"N": 1, "sweep": {"axis": "tau", "values": values},
           "fidelities": [[0.8], [0.7], [0.9]]}
    with pytest.raises(ValueError):
        periodogram_from_run(run)


def test_plot_run_sweep_consumes_recorded_dt_without_hardcoded_device_value():
    run = {"N": 1, "sweep": {"axis": "tau", "values": [0, 100]},
           "fidelities": [[0.8], [0.7]], "metadata": {"dt": 2e-9}}
    fig = plot_run_sweep(run, show=False)
    assert fig.axes[0].lines[0].get_xdata().tolist() == pytest.approx([0, 0.2])
    assert "us" in fig.axes[0].get_xlabel()
    plt.close(fig)
