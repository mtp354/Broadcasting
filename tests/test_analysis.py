"""Regression coverage for count statistics, uncertainty and exploratory spectra."""
import numpy as np
import pytest

from broadcasting.analysis import (delay_axis, hardware_scaling_points,
                                  joint_success_statistics, periodicity_summary)


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


from broadcasting.analysis import autocorrelation_from_run, periodogram_from_run

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

@pytest.mark.parametrize("values", [[0, 0, 1], [0, 1, 3], [0, 1, float("nan")]])
def test_periodicity_rejects_duplicate_irregular_or_nonfinite_grid(values):
    run = {"N": 1, "sweep": {"axis": "tau", "values": values},
           "fidelities": [[0.8], [0.7], [0.9]]}
    with pytest.raises(ValueError):
        periodogram_from_run(run)


def _scaling_run(*, job="job", case="all", repeat=0, m=1, n=2,
                 backend="ibm_kingston", phases=None, counts=None):
    """Loaded-record fixture with explicit physical identity and joint readout."""
    phases = [[0.1] * m] if phases is None else phases
    counts = [[{"0" * n: 10}]] if counts is None else counts
    return {
        "experiment_kind": "broadcasting", "experiment_type": "hardware",
        "optimization_level": 3, "use_qec": False, "M": m, "N": n,
        "backend": backend, "job_id": job, "filename": f"{job}_{case}.json",
        "timestamp": "", "shots": 10, "theta_samples": phases,
        "sweep": {"axis": "tau", "values": [0]}, "counts": counts,
        "fidelities": [[1.0] * n],
        "metadata": {"execution": {"experiment_id": "delay", "run_id": "run",
                                   "repeat_index": repeat, "case_id": case}},
    }


def test_scaling_point_recomputes_receiver_mean_and_range_at_actual_zero_delay():
    run = _scaling_run(n=3, counts=[[{"111": 10}, {"000": 4, "001": 3, "111": 3}]])
    run["sweep"]["values"] = [50, 0]
    # Neither a cached fidelity nor a top-level nominal shot count is the
    # numerical source: the selected histogram has marginals 0.4, 0.7, 0.7.
    run["fidelities"] = [[0.0] * 3, [1.0] * 3]
    run["shots"] = 999
    point, = hardware_scaling_points([run])
    assert point["shots"] == 10
    assert point["mean"] == pytest.approx(0.6)
    assert point["minimum"] == pytest.approx(0.4)
    assert point["maximum"] == pytest.approx(0.7)
    assert (point["M"], point["N"], point["x"]) == (1, 3, 3.0)


def test_scaling_retains_phases_distinct_cases_and_repetitions_without_pooling():
    from copy import deepcopy
    two_phases = _scaling_run(job="shared", phases=[[0.1], [0.2]],
                             counts=[[{"00": 10}], [{"11": 10}]])
    other_case = _scaling_run(job="shared", case="receiver0", phases=[[0.3]],
                             counts=[[{"01": 10}]])
    repetition = _scaling_run(job="other-job", repeat=1, phases=[[0.4]],
                             counts=[[{"00": 5, "11": 5}]])
    duplicate = deepcopy(two_phases)
    duplicate["filename"] = "another_save.json"
    points = hardware_scaling_points([two_phases, other_case, repetition, duplicate])
    assert len(points) == 4
    observed = {(p["job_id"], p["execution"]["case_id"], p["theta_index"],
                 tuple(p["thetas"]), p["mean"]) for p in points}
    assert observed == {
        ("shared", "all", 0, (0.1,), 1.0),
        ("shared", "all", 1, (0.2,), 0.0),
        ("shared", "receiver0", 0, (0.3,), 0.5),
        ("other-job", "all", 0, (0.4,), 0.5),
    }
    assert {p["x"] for p in points} == {2.0}


@pytest.mark.parametrize("change", [
    {"experiment_kind": "memory"},
    {"use_qec": True},
    {"experiment_type": "simulation"},
    {"optimization_level": 0},
    {"optimization_level": None},
    {"sweep": {"axis": "p", "values": [0]}},
    {"sweep": {"axis": "tau", "values": [50]}},
    {"sweep": {"axis": "tau", "values": [0, 0]}},
    {"counts": None},
    {"counts": []},
])
def test_scaling_requires_unencoded_opt3_hardware_with_one_zero_delay_histogram(change):
    excluded = _scaling_run(job="excluded")
    excluded.update(change)
    accepted = _scaling_run(job="accepted")
    points = hardware_scaling_points([excluded, accepted])
    assert [p["job_id"] for p in points] == ["accepted"]


def test_scaling_order_is_stable_when_input_discovery_order_changes():
    from itertools import permutations
    runs = [
        _scaling_run(job="large", n=3),
        _scaling_run(job="small", n=1, m=2),
        _scaling_run(job="kingston", n=2, backend="ibm_kingston"),
        _scaling_run(job="marrakesh", n=2, backend="ibm_marrakesh"),
    ]
    expected = hardware_scaling_points(runs)
    assert [point["N"] for point in expected] == [1, 2, 2, 3]
    for reordered in permutations(runs):
        assert hardware_scaling_points(list(reordered)) == expected
