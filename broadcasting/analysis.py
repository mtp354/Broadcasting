"""Read-only statistics of saved joint receiver readouts.

Intervals describe finite-shot uncertainty conditional on a fixed circuit/job/theta.
They do not include calibration drift, job-to-job variation, or physical-noise
model uncertainty. All receiver indices follow Qiskit's little-endian convention.
"""
from __future__ import annotations

from statistics import NormalDist
from typing import Any

import numpy as np


def delay_axis(run: dict[str, Any]) -> tuple[float, str]:
    """Use recorded seconds/dt, otherwise keep native dt; never guess a device dt."""
    dt = (run.get("metadata") or {}).get("dt")
    if dt is None:
        dt = run.get("dt")
    if dt is None:
        return 1.0, "dt"
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("Recorded dt must be finite and positive (seconds).")
    return float(dt) * 1e6, "us"


def wilson_interval(successes: float, shots: int, confidence: float = 0.95) -> list[float]:
    """Two-sided Wilson score interval for a binomial success proportion."""
    if shots <= 0 or not 0 <= successes <= shots or not 0 < confidence < 1:
        raise ValueError("Invalid binomial observations or confidence level.")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = successes / shots
    denom = 1 + z * z / shots
    center = (p + z * z / (2 * shots)) / denom
    half = z * np.sqrt(p * (1 - p) / shots + z * z / (4 * shots * shots)) / denom
    return [float(max(0.0, center - half)), float(min(1.0, center + half))]


def joint_success_statistics(counts: dict[str, int], n_receivers: int) -> dict[str, Any]:
    """Marginal/joint success, covariance, and paired asymmetry from one histogram.

    Covariance uses the empirical-distribution convention E[Xi Xj]-E[Xi]E[Xj].
    Standard errors for smooth statistics use the multinomial delta method with
    empirical influence functions; they are asymptotic and can degenerate when
    only one outcome is observed. The worst-receiver interval is constructed from
    Bonferroni-adjusted Wilson intervals, accounting for selection of the minimum.
    """
    if not isinstance(n_receivers, int) or n_receivers < 1 or not counts:
        raise ValueError("Need a positive receiver count and nonempty counts.")
    for bits, weight in counts.items():
        if len(bits) != n_receivers or set(bits) - {"0", "1"}:
            raise ValueError("Counts must contain exactly the receiver register bits.")
        if isinstance(weight, bool) or not isinstance(weight, (int, np.integer)) or weight < 0:
            raise ValueError("Histogram counts must be nonnegative integers.")
    total = int(sum(counts.values()))
    if total == 0:
        raise ValueError("Counts contain no shots.")
    x = np.array([[bit == "0" for bit in bits[::-1]] for bits in counts], dtype=float)
    weights = np.array(list(counts.values()), dtype=float)
    probabilities = weights / total
    local = probabilities @ x
    centered = x - local
    all_success = x.prod(axis=1)
    global_fidelity = float(probabilities @ all_success)
    product = float(local.prod())

    def smooth(value, influence, bounds=None):
        se = float(np.sqrt(max(0.0, probabilities @ (influence ** 2)) / total))
        ci = [float(value - 1.959963984540054 * se), float(value + 1.959963984540054 * se)]
        if bounds is not None:
            ci = [max(bounds[0], ci[0]), min(bounds[1], ci[1])]
        return {"estimate": float(value), "se": se, "ci95": ci}

    simultaneous = [wilson_interval(f * total, total, 1 - 0.05 / n_receivers) for f in local]
    pairs = []
    for i in range(n_receivers):
        for j in range(i + 1, n_receivers):
            pair_centered = centered[:, i] * centered[:, j]
            cov = float(probabilities @ pair_centered)
            diff = local[i] - local[j]
            pairs.append({
                "receivers": [i, j],
                "covariance": smooth(cov, pair_centered - cov, (-0.25, 0.25)),
                "fidelity_difference": smooth(diff, centered[:, i] - centered[:, j], (-1.0, 1.0)),
            })
    product_influence = sum(centered[:, i] * np.delete(local, i).prod() for i in range(n_receivers))
    return {
        "shots": total,
        "local_fidelities": local.tolist(),
        "local_ci95": [wilson_interval(f * total, total) for f in local],
        "mean_local": smooth(local.mean(), centered.mean(axis=1), (0.0, 1.0)),
        "worst_receiver": {
            "estimate": float(local.min()),
            "receiver": int(local.argmin()),
            "simultaneous_ci95": [min(v[0] for v in simultaneous), min(v[1] for v in simultaneous)],
        },
        "receiver_spread": float(np.ptp(local)),
        "global_fidelity": {
            "estimate": global_fidelity,
            "ci95": wilson_interval(global_fidelity * total, total),
        },
        "product_of_locals": smooth(product, product_influence, (0.0, 1.0)),
        "global_minus_product": smooth(global_fidelity - product, all_success - global_fidelity - product_influence, (-1.0, 1.0)),
        "pairs": pairs,
    }


def periodicity_summary(run: dict[str, Any], *, receiver: int | None = None) -> dict[str, Any]:
    """Exploratory dominant spectral peak with resolution and trend caveats.

    Linear detrending and a Hann window precede peak selection. No significance
    test is implied: selecting a peak, smooth drift, and ordered acquisition can
    all create apparent oscillations. Single points / sparse or irregular sweeps
    are reported as unavailable rather than assigned a period.
    """
    from scipy.signal import find_peaks
    from .plotting import _tau_fidelity_trace, autocorrelation_from_run, periodogram_from_run

    try:
        tau, trace = _tau_fidelity_trace(run, receiver=receiver)
    except ValueError as error:
        return {"status": "unavailable", "reason": str(error)}
    if tau.size < 8:
        return {"status": "unavailable", "reason": "Fewer than eight delay points."}
    trend_x = (tau - tau.mean()) / np.ptp(tau)
    trend = np.column_stack([np.ones(tau.size), trend_x])
    trend_resid = trace - trend @ np.linalg.lstsq(trend, trace, rcond=None)[0]
    baseline_sse = float(trend_resid @ trend_resid)
    numerical_floor = 1000 * np.finfo(float).eps ** 2 * tau.size * max(1.0, float(np.max(np.abs(trace)))) ** 2
    if baseline_sse <= numerical_floor:
        return {"status": "unavailable", "reason": "No resolved variance beyond a linear trend."}
    freqs, power = periodogram_from_run(run, receiver=receiver)
    if not np.any(power[1:] > 0):
        return {"status": "unavailable", "reason": "No nonzero spectral power."}
    peak = 1 + int(np.argmax(power[1:]))
    frequency = float(freqs[peak])
    period = 1 / frequency
    cycles = float((tau[-1] - tau[0]) / period)
    samples_per_period = float(period / (tau[1] - tau[0]))
    scale, unit = delay_axis(run)
    design = np.column_stack([trend, np.sin(2 * np.pi * frequency * tau), np.cos(2 * np.pi * frequency * tau)])
    coefficients = np.linalg.lstsq(design, trace, rcond=None)[0]
    residual = trace - design @ coefficients
    lags, ac = autocorrelation_from_run(run, receiver=receiver)
    peaks, _ = find_peaks(ac)
    positive_peaks = [i for i in peaks if ac[i] > 0]
    return {
        "status": "exploratory",
        "receiver": receiver,
        "points": int(tau.size),
        "time_unit": unit,
        "frequency": frequency / scale,
        "frequency_resolution": float(freqs[1] / scale),
        "dominant_period": period * scale,
        "cycles_in_observed_span": cycles,
        "few_cycles": cycles < 3,
        "samples_per_period": samples_per_period,
        "near_nyquist": samples_per_period < 4,
        "sinusoid_amplitude_at_selected_frequency": float(np.hypot(*coefficients[-2:])),
        "fraction_trend_residual_variance_explained": float(np.clip(1 - (residual @ residual) / baseline_sse, 0, 1)),
        "first_positive_ac_peak_lag": float(lags[positive_peaks[0]] * scale) if positive_peaks else None,
        "first_positive_ac_peak": float(ac[positive_peaks[0]]) if positive_peaks else None,
        "method": "Hann periodogram, linear detrending; uncorrected exploratory peak selection, no physical-mechanism attribution",
    }
