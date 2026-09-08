"""Data model for the broadcasting protocol configuration and results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np


@dataclass
class ProtocolConfig:
    """Parameters defining a single broadcasting protocol run.

    Parameters
    ----------
    M : int
        Number of sender qudits.
    N : int
        Number of receiver qubits.
    alpha : float
        Amplitude parameter for the initial state (|alpha| <= 1).
    thetas : list[float]
        Phase angles for each sender, length M.
    p_list : list[float]
        Depolarizing probabilities to sweep over.  Each value is applied
        uniformly to all N receivers.
    use_qec : bool
        Whether to use [[5,1,3]] quantum error correction on receiver qubits.
    outcomes_list : list[int] | None
        Fixed measurement outcomes for deterministic runs. If None, outcomes
        are sampled randomly.
    tau : float | None
        Delay time in backend dt units (used only by HardwareBackend).
    n_samples : int
        Number of Monte Carlo trajectories (used only by SamplingBackend).
    seed : int | None
        RNG seed for reproducibility.
    linear_feedforward : bool
        HardwareBackend only. If True (default), use the M*ceil(log2(N+1))
        single-bit-conditioned byproduct correction instead of the
        (N+1)**M-branch exponential feedforward.
    """

    M: int
    N: int
    alpha: float = 1 / np.sqrt(2)
    thetas: list[float] = field(default_factory=list)
    p_list: list[float] = field(default_factory=list)
    use_qec: bool = False
    outcomes_list: list[int] | None = None
    tau: float | None = None
    n_samples: Optional[int] = 200
    seed: int | None = None
    linear_feedforward: bool = True


@dataclass
class BroadcastResult:
    """Output of a broadcasting protocol run.

    Parameters
    ----------
    fidelities : list[float]
        Fidelity of each receiver's reduced state to the target state.
    target_state : np.ndarray | None
        Target single-qubit state vector (length 2).
    reduced_states : list[np.ndarray] | None
        Reduced density matrices (2x2) for each receiver.
    metadata : dict[str, Any]
        Run metadata including mode, backend, timestamp, etc.
    """

    fidelities: list[float]
    target_state: np.ndarray | None = None
    reduced_states: list[Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if "timestamp" not in self.metadata:
            self.metadata["timestamp"] = datetime.now().isoformat()
