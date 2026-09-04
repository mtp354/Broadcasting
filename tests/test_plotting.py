"""Tests for plotting helpers."""

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from broadcasting.plotting import (
    clear_titles,
    plot_fidelity_vs_noise,
    plot_run_sweep,
    save_figure,
)
from broadcasting.protocol import BroadcastResult, ProtocolConfig
from broadcasting.results import load_run, save_run


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
