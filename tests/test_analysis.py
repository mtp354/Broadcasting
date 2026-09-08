"""Regression coverage for count statistics, uncertainty and exploratory spectra."""
import numpy as np
import pytest

from broadcasting.analysis import delay_axis, joint_success_statistics, periodicity_summary


def test_independent_receivers_have_zero_covariance_and_correct_paired_uncertainty():
    result = joint_success_statistics({"00": 25, "01": 25, "10": 25, "11": 25}, 2)
    assert result["local_fidelities"] == [0.5, 0.5]
    assert result["global_fidelity"]["estimate"] == 0.25
    assert result["product_of_locals"]["estimate"] == 0.25
    pair = result["pairs"][0]
    assert pair["covariance"]["estimate"] == 0
    assert pair["covariance"]["se"] == pytest.approx(0.025)
    assert pair["fidelity_difference"]["se"] == pytest.approx(np.sqrt(0.5 / 100))
    assert result["mean_local"]["se"] == pytest.approx(np.sqrt(0.125 / 100))


def test_receiver_bit_order_and_asymmetry_are_paired():
    result = joint_success_statistics({"01": 75, "10": 25}, 2)
    assert result["local_fidelities"] == [0.25, 0.75]
    assert result["global_fidelity"]["estimate"] == 0
    pair = result["pairs"][0]
    assert pair["fidelity_difference"]["estimate"] == -0.5
    assert pair["fidelity_difference"]["se"] == pytest.approx(np.sqrt(0.75 / 100))
    assert pair["covariance"]["estimate"] == -0.1875


def test_joint_fidelity_is_not_replaced_by_product_of_marginals():
    result = joint_success_statistics({"00": 50, "11": 50}, 2)
    assert result["global_fidelity"]["estimate"] == 0.5
    assert result["product_of_locals"]["estimate"] == 0.25
    assert result["global_minus_product"]["estimate"] == 0.25
    # Correlation must increase the mean-receiver standard error.
    assert result["mean_local"]["se"] == pytest.approx(0.05)


def test_boundary_wilson_intervals_and_worst_receiver_selection():
    result = joint_success_statistics({"000": 100}, 3)
    assert result["global_fidelity"]["ci95"][0] < 1
    assert result["global_fidelity"]["ci95"][1] == pytest.approx(1)
    assert result["worst_receiver"]["simultaneous_ci95"][0] < result["local_ci95"][0][0]


@pytest.mark.parametrize("counts,n", [({}, 1), ({"00": 0}, 2), ({"00 0": 3}, 3), ({"00": -1}, 2), ({"00": 1.5}, 2), ({"0": 1}, 2)])
def test_malformed_histograms_rejected(counts, n):
    with pytest.raises(ValueError):
        joint_success_statistics(counts, n)


def test_unknown_dt_stays_native_and_recorded_dt_is_validated():
    assert delay_axis({}) == (1.0, "dt")
    assert delay_axis({"metadata": {"dt": None}}) == (1.0, "dt")
    scale, units = delay_axis({"metadata": {"dt": 4e-9}})
    assert scale == pytest.approx(0.004)
    assert units == "us"
    with pytest.raises(ValueError):
        delay_axis({"metadata": {"dt": -1}})


def test_periodicity_detects_known_period_and_flags_unresolved_sweeps():
    tau = np.arange(200) * 10
    trace = 0.7 + 0.1 * np.cos(2 * np.pi * tau / 200) + 0.00001 * tau
    run = {"N": 1, "sweep": {"axis": "tau", "values": tau.tolist()},
           "fidelities": trace[:, None].tolist(), "metadata": {"dt": 4e-9}}
    result = periodicity_summary(run)
    assert result["dominant_period"] == pytest.approx(0.8)
    assert result["frequency"] == pytest.approx(1.25)
    assert result["sinusoid_amplitude_at_selected_frequency"] == pytest.approx(0.1)
    assert not result["few_cycles"]
    assert not result["near_nyquist"]
    assert result["status"] == "exploratory"
    short = dict(run, sweep={"axis": "tau", "values": [0, 10, 20]}, fidelities=[[0.8], [0.7], [0.6]])
    assert periodicity_summary(short)["status"] == "unavailable"


@pytest.mark.parametrize("trace", [np.full(20, 0.5), np.full(20, 0.8), np.full(20, 1.0), np.linspace(0.4, 0.9, 20)])
def test_periodicity_does_not_promote_roundoff_of_constant_or_linear_trace(trace):
    run = {"N": 1, "sweep": {"axis": "tau", "values": list(range(20))},
           "fidelities": trace[:, None].tolist()}
    result = periodicity_summary(run)
    assert result["status"] == "unavailable"
    assert "linear trend" in result["reason"]
