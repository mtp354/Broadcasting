"""Plotting utilities for broadcasting protocol results."""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from .analysis import autocorrelation_from_run, delay_axis, joint_success_statistics, periodogram_from_run
from .validation import dedupe_by_job

FIGURES_DIR = Path("figures")


def clear_titles(fig: plt.Figure) -> None:
    """Remove figure and axes titles before exporting a publication figure."""
    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None:
        suptitle.remove()
        fig._suptitle = None

    for ax in fig.axes:
        for loc in ("left", "center", "right"):
            ax.set_title("", loc=loc)


def save_figure(
    fig: plt.Figure,
    path: str | Path,
    *,
    strip_titles: bool = True,
    dpi: int = 200,
    bbox_inches: str = "tight",
    **savefig_kwargs: Any,
) -> Path:
    """Save a PNG, stripping plot titles by default for publication exports."""
    path = Path(path)
    if path.suffix.lower() != ".png":
        raise ValueError("Figures are saved as PNG only; use a .png filename.")
    if str(savefig_kwargs.pop("format", "png")).lower() != "png":
        raise ValueError("Figures are saved as PNG only.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if strip_titles:
        clear_titles(fig)
    fig.savefig(path, format="png", dpi=dpi, bbox_inches=bbox_inches, **savefig_kwargs)
    return path


def binomial_error(p: float, n: int) -> float:
    """Standard error for a binomial proportion."""
    return np.sqrt(p * (1 - p) / n) if n > 0 else 0.0


def _meta_text(run: dict[str, Any], extra_lines: list[str] | None = None) -> str:
    """Build the metadata annotation string for a plot.

    Includes a **Mode** line derived from the run's metadata.
    """
    mode = run.get("metadata", {}).get("mode", run.get("backend", "simulation"))
    qec_str = "QEC [[5,1,3]]" if run.get("use_qec") else "No QEC"

    lines = [f"Mode: {mode}"]

    backend = run.get("backend", "")
    if backend and backend not in mode:
        lines.append(f"Backend: {backend}")

    lines.append(f"M={run['M']}, N={run['N']}, {qec_str}")

    theta_samples = run.get("theta_samples", [[]])
    nt = run.get("nt", 1)
    if nt > 1:
        lines.append(f"Thetas: {nt} random samples")
    elif theta_samples and theta_samples[0]:
        lines.append(
            f"Thetas: [{', '.join(f'{t:.3f}' for t in theta_samples[0])}]"
        )

    shots = run.get("shots", 0)
    if shots:
        lines.append(f"Shots: {shots:,}")

    job_id = run.get("job_id", "")
    if job_id:
        display_id = f"{job_id[:16]}..." if len(job_id) > 16 else job_id
        lines.append(f"Job: {display_id}")

    ts = run.get("timestamp", "")
    if ts:
        lines.append(f"Time: {ts[:19]}")

    if extra_lines:
        lines.extend(extra_lines)

    return "\n".join(lines)


def _add_meta_box(ax: plt.Axes, text: str) -> None:
    """Place a metadata annotation box in the lower-right corner."""
    ax.text(
        0.98,
        0.02,
        text,
        transform=ax.transAxes,
        fontsize=7,
        verticalalignment="bottom",
        horizontalalignment="right",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="wheat", alpha=0.7),
    )


# ---------------------------------------------------------------------------
# Hardware / delay plots
# ---------------------------------------------------------------------------

def hardware_scaling_points(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one opt3, zero-delay point per job/case/theta, without pooling.

    Fidelity and receiver ranges are recomputed from saved joint counts. Small,
    deterministic horizontal offsets separate observations with the same N;
    the integer receiver count remains available as ``N`` alongside ``x``.
    """
    points = []
    for run in dedupe_by_job(runs):
        if (run.get("experiment_type") != "hardware"
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
                "M": run["M"], "N": run["N"], "backend": run.get("backend", "unknown"),
                "timestamp": run.get("timestamp", ""), "job_id": run.get("job_id"),
                "filename": run.get("filename", ""), "shots": stats["shots"],
                "theta_index": theta_index,
                "thetas": run.get("theta_samples", [[]])[theta_index],
                "campaign": (run.get("metadata") or {}).get("campaign", {}),
                "mean": stats["mean_local"]["estimate"],
                "minimum": min(local), "maximum": max(local),
            })
    points.sort(key=lambda point: (point["N"], point["M"], point["backend"],
                                   point["timestamp"], str(point["job_id"]),
                                   point["campaign"].get("run_id", ""),
                                   point["campaign"].get("repeat_index", -1),
                                   point["campaign"].get("case_id", ""),
                                   point["filename"], point["theta_index"]))
    for receivers in sorted({point["N"] for point in points}):
        group = [point for point in points if point["N"] == receivers]
        offsets = np.linspace(-0.22, 0.22, len(group)) if len(group) > 1 else [0.0]
        for point, offset in zip(group, offsets):
            point["x"] = float(receivers + offset)
    return points


def plot_hardware_scaling(runs: list[dict[str, Any]]) -> plt.Figure:
    """Opt3 hardware fidelity versus receivers; color identifies sender count.

    Dots show the receiver mean and capped vertical bars show the receiver
    minimum/maximum, not statistical uncertainty. Backend marker shapes and
    horizontal offsets retain distinct observations. ``fig.broadcasting_points``
    contains the complete plotted identities and values for notebook inspection.
    """
    points = hardware_scaling_points(runs)
    if not points:
        raise ValueError("No opt3 saved joint receiver counts at tau=0.")
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    fig.broadcasting_points = points
    senders = sorted({point["M"] for point in points})
    backends = sorted({point["backend"] for point in points})
    colors = {sender: plt.cm.tab10((sender - 1) % 10) for sender in senders}
    marker_options = ["o", "s", "^", "D", "v", "P", "X"]
    markers = {backend: marker_options[index % len(marker_options)]
               for index, backend in enumerate(backends)}
    for point in points:
        mean = point["mean"]
        ax.errorbar(point["x"], mean,
                    yerr=[[max(0.0, mean - point["minimum"])],
                          [max(0.0, point["maximum"] - mean)]],
                    fmt=markers[point["backend"]], color=colors[point["M"]],
                    markersize=5.5, capsize=3, linewidth=1.4, alpha=0.85)
    handles = [Line2D([], [], color=colors[m], marker="o", linestyle="none",
                      label=f"M = {m} sender{'s' if m != 1 else ''}") for m in senders]
    handles += [Line2D([], [], color="0.3", marker=markers[backend], linestyle="none",
                       label=backend.removeprefix("ibm_")) for backend in backends]
    ax.legend(handles=handles, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.02),
              ncol=min(4, len(handles)), frameon=False)
    receivers = sorted({point["N"] for point in points})
    ax.set_xticks(range(min(receivers), max(receivers) + 1))
    ax.set(xlabel="Number of receivers, N", ylabel="Receiver fidelity at zero delay",
           xlim=(min(receivers) - 0.5, max(receivers) + 0.5), ylim=(0, 1.02))
    ax.axhline(0.5, color="0.6", linestyle=":", linewidth=1)
    ax.grid(axis="y", alpha=0.2)
    fig.text(0.5, 0.015,
             "Opt3 only · point = receiver mean · bar = receiver range\n"
             "Horizontal offsets separate jobs, cases and phase samples; observations are not pooled.",
             ha="center", fontsize=8, color="0.3")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    return fig


def plot_delay_repeats(runs: list[dict[str, Any]], *, max_columns: int = 2) -> plt.Figure:
    """Plot each saved delay sweep and phase sample in its own labelled panel.

    Receivers retain separate curves and marginal 95% Wilson shot intervals.
    Time uses each record's archived dt; unknown conversions remain native dt.
    No averaging across random angles, jobs, or repeats is performed.
    """
    if max_columns < 1:
        raise ValueError("max_columns must be positive.")
    traces = []
    for run in dedupe_by_job(runs):
        if (run.get("experiment_type") == "hardware"
                and run.get("sweep", {}).get("axis") == "tau"
                and len(run["sweep"]["values"]) > 1 and run.get("counts")):
            traces.extend((run, index, row) for index, row in enumerate(run["counts"]))
    if not traces:
        raise ValueError("No saved hardware delay sweeps with receiver counts.")
    columns = min(max_columns, len(traces))
    rows = int(np.ceil(len(traces) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(6.3 * columns, 4.2 * rows),
                             squeeze=False, sharey=True)
    for ax, (run, theta_index, counts) in zip(axes.flat, traces):
        scale, unit = delay_axis(run)
        delays = np.asarray(run["sweep"]["values"], dtype=float)
        order = np.argsort(delays)
        statistics = [joint_success_statistics(counts[index], run["N"]) for index in order]
        local = np.asarray([point["local_fidelities"] for point in statistics])
        intervals = np.asarray([point["local_ci95"] for point in statistics])
        for receiver in range(run["N"]):
            values = local[:, receiver]
            errors = np.maximum(0, np.vstack((values - intervals[:, receiver, 0],
                                             intervals[:, receiver, 1] - values)))
            ax.errorbar(scale * delays[order], values, yerr=errors, fmt="o-",
                        color=plt.cm.tab10(receiver % 10), markersize=2.5,
                        linewidth=1, elinewidth=0.5, alpha=0.85,
                        label=f"Receiver {receiver + 1}")
        ax.plot(scale * delays[order], local.mean(axis=1), "k--", linewidth=1.2, label="Mean")
        campaign = (run.get("metadata") or {}).get("campaign", {})
        identity = f"job {run.get('job_id', '?')}"
        if campaign:
            identity += f" · repeat {campaign['repeat_index']} · {campaign['case_id']}"
        thetas = run.get("theta_samples", [[]])[theta_index]
        phase = ", ".join(f"{theta:.3f}" for theta in thetas)
        label = (f"{run.get('backend')} · M={run['M']}, N={run['N']} · opt{run.get('optimization_level')} "
                 f"· {run.get('shots', '?')} shots\nθ{theta_index} = [{phase}] rad · {run.get('timestamp', '')[:10]}\n"
                 f"{identity}")
        factors = campaign.get("receiver_delay_factors")
        if factors:
            label += f"\nReceiver delay factors: {factors}; x is the base delay"
        ax.text(0, 1.025, label, transform=ax.transAxes, fontsize=7, va="bottom")
        ax.set(xlabel=f"Idle delay ({unit})", ylabel="Receiver fidelity", ylim=(0, 1.02))
        ax.axhline(0.5, color="0.6", linestyle=":", linewidth=1)
        ax.grid(alpha=0.2)
        ax.legend(fontsize=7, loc="best")
    for ax in list(axes.flat)[len(traces):]:
        ax.set_visible(False)
    fig.text(0.5, 0.005, "Error bars: marginal 95% Wilson shot intervals; device drift is not included.",
             ha="center", fontsize=8, color="0.3")
    fig.tight_layout(rect=(0, 0.025, 1, 1), h_pad=4)
    return fig

def plot_fidelity_vs_delay(
    run: dict[str, Any],
    *,
    ax: plt.Axes | None = None,
    show_title: bool = False,
    show: bool = True,
) -> plt.Figure:
    """Fidelity vs delay time with error bars (hardware results).

    Parameters
    ----------
    run : dict
        Loaded run record (from :func:`broadcasting.results.load_run`).
    ax : Axes or None
        Matplotlib axes to plot on.  Created if None.
    show : bool
        Call ``plt.show()`` at the end.

    Returns
    -------
    Figure
    """
    N = run["N"]
    shots = run["shots"]
    entries = run["entries"]

    tau_data: dict[int, list] = {}
    for e in entries:
        tau_data.setdefault(e["tau"], []).append(e["fidelities"])

    taus = sorted(tau_data.keys())
    scale, unit = delay_axis(run)
    plotted_taus = np.asarray(taus) * scale
    recv_means = np.zeros((N, len(taus)))
    recv_errs = np.zeros((N, len(taus)))

    for j, tau in enumerate(taus):
        fid_matrix = np.array(tau_data[tau])
        for i in range(N):
            fids = fid_matrix[:, i]
            mean_fid = np.mean(fids)
            shot_err = np.mean([binomial_error(f, shots) for f in fids])
            theta_err = (
                np.std(fids) / np.sqrt(len(fids)) if len(fids) > 1 else 0.0
            )
            recv_means[i, j] = mean_fid
            recv_errs[i, j] = np.sqrt(shot_err ** 2 + theta_err ** 2)

    avg_means = np.mean(recv_means, axis=0)
    avg_errs = np.sqrt(np.sum(recv_errs ** 2, axis=0)) / N

    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 6))
    else:
        fig = ax.figure

    colors = plt.cm.tab10.colors
    for i in range(N):
        ax.errorbar(
            plotted_taus,
            recv_means[i],
            yerr=recv_errs[i],
            fmt="o-",
            color=colors[i % len(colors)],
            capsize=3,
            markersize=4,
            linewidth=1,
            alpha=0.7,
            label=f"Receiver {i}",
        )

    ax.errorbar(
        plotted_taus,
        avg_means,
        yerr=avg_errs,
        fmt="s--",
        color="black",
        capsize=4,
        markersize=5,
        linewidth=1.5,
        label="Average",
    )
    ax.axhline(0.5, color="gray", linestyle=":", alpha=0.5, label="Random (0.5)")

    ax.set_xlabel(f"Delay time ({unit})")
    ax.set_ylabel("Fidelity P(0)")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="best", fontsize=9)
    _add_meta_box(ax, _meta_text(run))
    if show_title:
        ax.set_title(f"Fidelity vs Delay - {run.get('filename', '')}")

    if show:
        plt.tight_layout()
        plt.show()
    return fig


# ---------------------------------------------------------------------------
# Simulation sweep plots
# ---------------------------------------------------------------------------

def plot_fidelity_vs_noise(
    p_values: np.ndarray,
    fidelity_arrays: dict[str, np.ndarray],
    *,
    mode_label: str = "Exact Simulation",
    title: str = "Fidelity vs Depolarizing Probability",
    protocol_info: dict[str, Any] | None = None,
    ax: plt.Axes | None = None,
    show_title: bool = False,
    show: bool = True,
) -> plt.Figure:
    """Plot receiver fidelities as a function of noise strength.

    Parameters
    ----------
    p_values : array
        Depolarizing probabilities swept.
    fidelity_arrays : dict[str, array]
        Mapping ``"Receiver i"`` -> fidelity array (same length as
        *p_values*).
    mode_label : str
        Simulation mode shown in the metadata box.
    title : str
        Plot title.
    protocol_info : dict or None
        Additional metadata for the annotation box.
    ax : Axes or None
        Matplotlib axes.
    show : bool
        Call ``plt.show()``.

    Returns
    -------
    Figure
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 6))
    else:
        fig = ax.figure

    colors = plt.cm.tab10.colors
    for idx, (label, fids) in enumerate(fidelity_arrays.items()):
        ax.plot(
            p_values,
            fids,
            "-o",
            color=colors[idx % len(colors)],
            markersize=3,
            linewidth=1,
            label=label,
        )

    ax.axhline(0.5, color="gray", linestyle=":", alpha=0.5)
    ax.set_xlabel("Depolarizing probability p")
    ax.set_ylabel("Fidelity")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, 1)
    ax.legend(loc="best", fontsize=9)
    if show_title:
        ax.set_title(title)

    if protocol_info is not None:
        meta = {
            "metadata": {"mode": mode_label},
            **protocol_info,
        }
        _add_meta_box(ax, _meta_text(meta))
    else:
        _add_meta_box(ax, f"Mode: {mode_label}")

    if show:
        plt.tight_layout()
        plt.show()
    return fig


def plot_3d_fidelity(
    points: np.ndarray,
    *,
    mode_label: str = "Exact Simulation",
    title: str = "Fidelity between Receiver States",
    protocol_info: dict[str, Any] | None = None,
    show_title: bool = False,
    show: bool = True,
) -> plt.Figure:
    """3D scatter plot of pairwise receiver fidelities.

    Parameters
    ----------
    points : array, shape (3, n_points)
        Row 0: target fidelity receiver A, row 1: target fidelity
        receiver B, row 2: pairwise fidelity.
    mode_label : str
        Simulation mode label.
    title : str
        Plot title.
    protocol_info : dict or None
        Additional metadata.
    show : bool
        Call ``plt.show()``.

    Returns
    -------
    Figure
    """
    fig = plt.figure(figsize=(10, 10))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(points[0], points[1], points[2], c=points[2], cmap="viridis", s=50)

    xx, yy = np.meshgrid(np.linspace(0, 1, 10), np.linspace(0, 1, 10))
    ax.plot_surface(xx, yy, 0.5 * np.ones_like(xx), color="gray", alpha=0.3)

    ax.set_xlabel("Target Fidelity Receiver A")
    ax.set_ylabel("Target Fidelity Receiver B")
    ax.set_zlabel("Pairwise Fidelity")
    ax.view_init(elev=10, azim=30)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_zlim(0, 1)
    if show_title:
        ax.set_title(f"{title}\nMode: {mode_label}")

    if show:
        plt.tight_layout()
        plt.show()
    return fig


def plot_run_sweep(
    run: dict[str, Any],
    *,
    ax: plt.Axes | None = None,
    tau_scale: float | None = None,
    tau_label: str = "Idle delay (dt)",
    show_average: bool = True,
    show: bool = True,
) -> plt.Figure:
    """Plot a loaded run over its saved sweep axis without adding a title."""
    sweep = run.get("sweep", {}) or {}
    axis = sweep.get("axis", "p")
    x_values = np.asarray(sweep.get("values", []), dtype=float)
    fids = np.asarray(run["fidelities"], dtype=float)
    if fids.ndim == 1:
        fids = fids.reshape(1, -1)

    if axis == "p":
        xlabel = "Depolarizing probability p"
        xlim = (0.0, 1.0)
    elif axis == "tau":
        if tau_scale is None:
            tau_scale, unit = delay_axis(run)
            tau_label = f"Idle delay ({unit})"
        if not np.isfinite(tau_scale) or tau_scale <= 0:
            raise ValueError("tau_scale must be finite and positive.")
        x_values = tau_scale * x_values
        xlabel = tau_label
        xlim = (float(x_values.min()), float(x_values.max())) if x_values.size > 1 else None
    else:
        xlabel = axis
        xlim = None

    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 6))
    else:
        fig = ax.figure

    colors = plt.cm.tab10.colors
    for i in range(fids.shape[1]):
        ax.plot(
            x_values,
            fids[:, i],
            "-",
            color=colors[i % len(colors)],
            linewidth=1.2,
            label=f"Receiver {i}",
        )

    if show_average and fids.shape[1] > 1:
        ax.plot(
            x_values,
            fids.mean(axis=1),
            "k--",
            linewidth=1.5,
            label="Average",
        )

    ax.axhline(0.5, color="gray", linestyle=":", alpha=0.5, label="Random (0.5)")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Fidelity")
    ax.set_ylim(0, 1.05)
    if xlim is not None:
        ax.set_xlim(*xlim)
    ax.legend(loc="best", fontsize=9)

    if show:
        plt.tight_layout()
        plt.show()
    return fig


# ---------------------------------------------------------------------------
# Delay-sweep periodicity analysis (autocorrelation / periodogram)
# ---------------------------------------------------------------------------

def plot_periodicity_comparison(
    runs: list[dict[str, Any]],
    labels: list[str],
    *,
    receiver: int | None = None,
    tau_scale: float | None = None,
    tau_label: str = "Idle delay (dt)",
    show: bool = True,
) -> plt.Figure:
    """Side-by-side autocorrelation and periodogram comparison across runs.

    Intended for comparing tau-sweep fidelity traces collected with different
    settings (e.g. optimization levels or repetition runs) without asserting a
    conclusion about a shared cause.
    """
    if len(runs) != len(labels):
        raise ValueError("runs and labels must be the same length.")

    if tau_scale is not None and (not np.isfinite(tau_scale) or tau_scale <= 0):
        raise ValueError("tau_scale must be finite and positive.")

    fig, (ax_ac, ax_psd) = plt.subplots(1, 2, figsize=(12, 5))
    colors = plt.cm.tab10.colors

    for i, (run, label) in enumerate(zip(runs, labels)):
        color = colors[i % len(colors)]
        lags, ac = autocorrelation_from_run(run, receiver=receiver)
        freqs, power = periodogram_from_run(run, receiver=receiver)

        scale = tau_scale if tau_scale is not None else 1.0
        lag_x = scale * lags
        ax_ac.plot(lag_x, ac, color=color, label=label)
        # Changing t' = scale*t gives f' = f/scale and S' = scale*S,
        # preserving the integrated spectral power (variance).
        ax_psd.plot(freqs / scale, power * scale, color=color, label=label)

    ax_ac.axhline(0.0, color="gray", linestyle=":", alpha=0.5)
    unit = tau_label.split("(")[-1].rstrip(")") if "(" in tau_label else "tau"
    ax_ac.set_xlabel(f"Lag ({unit})")
    ax_ac.set_ylabel("Autocorrelation")
    ax_ac.legend(loc="best", fontsize=9)

    ax_psd.set_xlabel(f"Frequency (cycles/{unit})")
    ax_psd.set_ylabel(f"Power spectral density (fidelity² {unit})")
    ax_psd.legend(loc="best", fontsize=9)

    if show:
        plt.tight_layout()
        plt.show()
    return fig
