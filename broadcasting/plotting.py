"""Plotting utilities for broadcasting protocol results."""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

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
    dpi: int = 150,
    bbox_inches: str = "tight",
    **savefig_kwargs: Any,
) -> Path:
    """Save *fig*, stripping plot titles by default."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if strip_titles:
        clear_titles(fig)
    fig.savefig(path, dpi=dpi, bbox_inches=bbox_inches, **savefig_kwargs)
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
            taus,
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
        taus,
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

    ax.set_xlabel("Delay time (dt)")
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
        if tau_scale is not None:
            x_values = tau_scale * x_values
        xlabel = tau_label
        xlim = (float(x_values.min()), float(x_values.max())) if x_values.size else None
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
