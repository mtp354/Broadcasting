"""Regression coverage for count statistics, uncertainty and hardware scaling."""
import numpy as np
import pytest

from broadcasting.analysis import (delay_axis, hardware_scaling_points,
                                  joint_success_statistics)


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
