"""Read-only statistics of saved joint receiver readouts.

Intervals describe finite-shot uncertainty conditional on a fixed circuit/job/theta.
They do not include calibration drift, job-to-job variation, or physical-noise
model uncertainty. All receiver indices follow Qiskit's little-endian convention.
"""
from __future__ import annotations

from statistics import NormalDist
from typing import Any

import numpy as np

from .validation import dedupe_by_job
from .provenance import execution_summary


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
    # Columns follow receiver indices, so reverse Qiskit's displayed bit order.
    success = np.array([[bit == "0" for bit in bits[::-1]] for bits in counts], dtype=float)
    weights = np.array(list(counts.values()), dtype=float)
    probabilities = weights / total
    local = probabilities @ success
    centered = success - local
    all_success = success.prod(axis=1)
    global_fidelity = float(probabilities @ all_success)
    product = float(local.prod())

    def smooth(value, influence, bounds):
        """Estimate and delta-method interval under this empirical histogram."""
        se = float(np.sqrt(max(0.0, probabilities @ (influence ** 2)) / total))
        half_width = NormalDist().inv_cdf(0.975) * se
        ci = [max(bounds[0], float(value - half_width)),
              min(bounds[1], float(value + half_width))]
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


def hardware_scaling_points(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one opt3, zero-delay point per job/case/theta, without pooling.

    Fidelity and receiver ranges are recomputed from saved joint counts.
    Display offsets and all other visual choices belong to the notebook.
    """
    points = []
    for run in dedupe_by_job(runs):
        if (run.get("experiment_kind", "broadcasting") != "broadcasting"
                or run.get("use_qec", False)
                or run.get("experiment_type") != "hardware"
                or run.get("optimization_level") != 3
                or run.get("sweep", {}).get("axis") != "tau"):
            continue
        zero = np.flatnonzero(np.asarray(run["sweep"]["values"]) == 0)
        if len(zero) != 1 or not run.get("counts"):
            continue
        for theta_index, row in enumerate(run["counts"]):
            stats = joint_success_statistics(row[int(zero[0])], run["N"])
            local = stats["local_fidelities"]
            points.append({
                "M": run["M"], "N": run["N"], "x": float(run["N"]), "backend": run.get("backend", "unknown"),
                "timestamp": run.get("timestamp", ""), "job_id": run.get("job_id"),
                "filename": run.get("filename", ""), "shots": stats["shots"],
                "theta_index": theta_index,
                "thetas": run.get("theta_samples", [[]])[theta_index],
                "record_id": run.get("record_id"), "execution": execution_summary(run),
                "mean": stats["mean_local"]["estimate"],
                "minimum": min(local), "maximum": max(local),
            })
    points.sort(key=lambda point: (point["N"], point["M"], point["backend"],
                                   point["timestamp"], str(point["job_id"]),
                                   point["execution"].get("run_id", ""),
                                   point["execution"].get("repeat_index", -1),
                                   point["execution"].get("case_id", ""),
                                   point["filename"], point["theta_index"]))
    return points
