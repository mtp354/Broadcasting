"""Local simulation of the M-sender, N-receiver broadcasting protocol.

Provides exact density-matrix and Monte Carlo Pauli-trajectory simulation
paths, with optional [[5,1,3]] quantum error correction.  All functions
operate on native qudit dimensions (dim = N+1 per sender) — no binary
qubit encoding is needed.
"""

import itertools
import warnings
from typing import Any

import numpy as np
from qiskit.quantum_info import DensityMatrix, Pauli, Statevector, state_fidelity

from .qec_513 import five_qubit_logical_basis, pauli_label_syndrome


def _apply_state_operator(
    state_tensor: np.ndarray, operator: np.ndarray, axis: int
) -> np.ndarray:
    """Apply a local operator, retaining the position of its tensor axis."""
    result = np.tensordot(operator, state_tensor, axes=([1], [axis]))
    return np.moveaxis(result, 0, axis)


def _apply_density_operator(
    density_tensor: np.ndarray, operator: np.ndarray, axis: int
) -> np.ndarray:
    """Apply ``operator @ rho @ operator†`` on one subsystem's ket/bra axes."""
    bra_axis = density_tensor.ndim // 2 + axis
    result = _apply_state_operator(density_tensor, operator, axis)
    result = np.tensordot(result, operator.conj().T, axes=([bra_axis], [0]))
    return np.moveaxis(result, -1, bra_axis)


# ---------------------------------------------------------------------------
# Partial trace
# ---------------------------------------------------------------------------

def partial_trace_np(
    rho: DensityMatrix,
    dims: tuple[int, ...],
    keep: list[int],
) -> np.ndarray:
    """Partial trace of a density matrix over a product Hilbert space.

    Parameters
    ----------
    rho : DensityMatrix
        Full density matrix.
    dims : tuple[int, ...]
        Local dimensions of each subsystem, e.g. ``(3, 2, 2)``.
    keep : list[int]
        Indices of subsystems to keep.

    Returns
    -------
    np.ndarray
        Reduced density matrix on the kept subsystems.
    """
    dims = list(dims)
    n_sub = len(dims)
    keep = sorted(keep)
    trace_out = [i for i in range(n_sub) if i not in keep]

    rho_mat = rho.data
    rho_t = rho_mat.reshape(dims + dims)

    for s in sorted(trace_out, reverse=True):
        rho_t = np.trace(rho_t, axis1=s, axis2=s + len(dims))
        dims.pop(s)

    d_kept = int(np.prod(dims)) if dims else 1
    return rho_t.reshape(d_kept, d_kept)


# ---------------------------------------------------------------------------
# Initial state preparation
# ---------------------------------------------------------------------------

def get_initial_state(
    M: int,
    N: int,
    alpha: complex = 1 / np.sqrt(2),
) -> Statevector:
    r"""Construct the broadcast resource state :math:`|\Psi^{(M,N)}\rangle`.

    The Hilbert space has dimension :math:`(N+1)^M \times 2^N`, with *M*
    sender qudits (each of dimension *N* + 1) followed by *N* receiver
    qubits.

    Parameters
    ----------
    M : int
        Number of sender qudits.
    N : int
        Number of receiver qubits.
    alpha : complex
        Amplitude parameter (|alpha| <= 1).

    Returns
    -------
    Statevector
    """
    beta = np.sqrt(1 - abs(alpha) ** 2)
    d_qudit = N + 1
    dim_qubits = 2 ** N
    dim_total = (d_qudit ** M) * dim_qubits

    state = np.zeros(dim_total, dtype=complex)

    # Every sender carries the same qudit value k in each resource-state term.
    sender_stride = sum(d_qudit**sender for sender in range(M))
    for k in range(N + 1):
        amplitude = alpha**k * beta ** (N - k)
        sender_index = k * sender_stride

        for zeros in itertools.combinations(range(N), k):
            receiver_index = (1 << N) - 1
            for receiver in zeros:
                receiver_index &= ~(1 << (N - 1 - receiver))
            state[sender_index * dim_qubits + receiver_index] = amplitude

    return Statevector(state)


# ---------------------------------------------------------------------------
# Depolarizing noise (bare, non-QEC)
# ---------------------------------------------------------------------------

def depolarizing_channels(
    M: int,
    N: int,
    rho: DensityMatrix,
    p_list: list[float],
) -> DensityMatrix:
    """Apply independent depolarizing channels to each receiver qubit.

    Parameters
    ----------
    M : int
        Number of sender qudits.
    N : int
        Number of receiver qubits.
    rho : DensityMatrix
        Input density matrix on the full Hilbert space.
    p_list : list[float]
        Depolarizing probability per receiver.

    Returns
    -------
    DensityMatrix
    """
    rho_mat = rho.data
    total_receivers = len(p_list)
    X = Pauli("X").to_matrix()
    Y = Pauli("Y").to_matrix()
    Z = Pauli("Z").to_matrix()

    for i, p in enumerate(p_list):
        left_dim = (N + 1) ** M * (2 ** i)
        right_dim = 2 ** (total_receivers - i - 1)
        I_left = np.eye(left_dim)
        I_right = np.eye(right_dim)

        evolve_x = np.kron(np.kron(I_left, X), I_right)
        evolve_y = np.kron(np.kron(I_left, Y), I_right)
        evolve_z = np.kron(np.kron(I_left, Z), I_right)

        rho_mat = (1 - p) * rho_mat + (p / 3) * (
            evolve_x @ rho_mat @ evolve_x.conj().T
            + evolve_y @ rho_mat @ evolve_y.conj().T
            + evolve_z @ rho_mat @ evolve_z.conj().T
        )
    return DensityMatrix(rho_mat)


# ---------------------------------------------------------------------------
# Sender unitaries, measurement, correction
# ---------------------------------------------------------------------------

def apply_alice_unitaries(
    M: int,
    N: int,
    rho: DensityMatrix,
    theta_list: list[float],
) -> DensityMatrix:
    """Apply diagonal phase unitaries to each sender qudit.

    Parameters
    ----------
    M : int
        Number of sender qudits.
    N : int
        Number of receiver qubits.
    rho : DensityMatrix
        Input density matrix.
    theta_list : list[float]
        Phase angle per sender, length *M*.

    Returns
    -------
    DensityMatrix
    """
    rho_mat = rho.data
    theta_list = np.asarray(theta_list, dtype=float)

    k = np.arange(N + 1, dtype=float)
    single = [
        np.diag(np.exp(1j * (2.0 * k - float(N)) * theta_list[j]))
        for j in range(M)
    ]

    U_A = single[0]
    for j in range(1, M):
        U_A = np.kron(U_A, single[j])

    U = np.kron(U_A, np.eye(2 ** N, dtype=complex))
    return DensityMatrix(U @ rho_mat @ U.conj().T)


def measure_alices(
    M: int,
    N: int,
    rho: DensityMatrix,
    outcomes_list: list[int] | None = None,
    seed: int | None = None,
) -> tuple[DensityMatrix, list[int]]:
    """Fourier-basis measurement on each sender qudit.

    Parameters
    ----------
    M : int
        Number of sender qudits.
    N : int
        Number of receiver qubits.
    rho : DensityMatrix
        Input density matrix.
    outcomes_list : list[int] | None
        If given, use these deterministic outcomes instead of sampling.
    seed : int | None
        RNG seed (ignored when *outcomes_list* is provided).

    Returns
    -------
    DensityMatrix
        Post-measurement state (projected and renormalized).
    list[int]
        Measurement outcomes.
    """
    rho_mat = rho.data
    d = N + 1

    k = np.arange(d)
    P_single = []
    for n in range(d):
        u = np.exp(2j * np.pi * n * k / d) / np.sqrt(d)
        P_single.append(np.outer(u, u.conj()))

    rng = np.random.default_rng(seed)
    outcomes: list[int] = []

    for j in range(M):
        left_dim = d ** j
        right_dim = (d ** (M - j - 1)) * (2 ** N)
        I_left = np.eye(left_dim, dtype=complex)
        I_right = np.eye(right_dim, dtype=complex)

        if outcomes_list is None:
            probs = np.empty(d, dtype=float)
            for n in range(d):
                Pi = np.kron(I_left, np.kron(P_single[n], I_right))
                probs[n] = float(np.real(np.trace(Pi @ rho_mat)))
            probs = probs / probs.sum()
            n_out = int(rng.choice(d, p=probs))
        else:
            n_out = int(outcomes_list[j])

        outcomes.append(n_out)
        Pi = np.kron(I_left, np.kron(P_single[n_out], I_right))
        p_val = np.trace(Pi @ rho_mat)
        rho_mat = (Pi @ rho_mat @ Pi) / p_val

    return DensityMatrix(rho_mat), outcomes


def apply_corrections(
    M: int,
    N: int,
    rho: DensityMatrix,
    outcomes_list: list[int],
) -> DensityMatrix:
    """Apply phase corrections to receivers based on sender measurement outcomes.

    Parameters
    ----------
    M : int
        Number of sender qudits.
    N : int
        Number of receiver qubits.
    rho : DensityMatrix
        Post-measurement density matrix.
    outcomes_list : list[int]
        Sender measurement outcomes.

    Returns
    -------
    DensityMatrix
    """
    rho_mat = rho.data
    d = N + 1
    outcomes_arr = np.asarray(outcomes_list, dtype=int)
    phi = 2.0 * np.pi * outcomes_arr.sum() / d

    U1 = np.array([[np.exp(1j * phi), 0.0], [0.0, 1.0]], dtype=complex)
    UR = U1
    for _ in range(1, N):
        UR = np.kron(UR, U1)

    U = np.kron(np.eye(d ** M, dtype=complex), UR)
    return DensityMatrix(U @ rho_mat @ U.conj().T)


# ---------------------------------------------------------------------------
# [[5,1,3]] QEC encoding
# ---------------------------------------------------------------------------

def encode_initial_state(
    state: Statevector,
    M: int,
    N: int,
) -> Statevector:
    r"""Encode each receiver qubit into a [[5,1,3]] code block.

    Maps dimension :math:`(N+1)^M \times 2^N` to
    :math:`(N+1)^M \times 2^{5N}`.

    Parameters
    ----------
    state : Statevector
        Unencoded state.
    M : int
        Number of sender qudits.
    N : int
        Number of receiver qubits.

    Returns
    -------
    Statevector
        Encoded state with 5 physical qubits per receiver.
    """
    d = N + 1
    expected_dim = (d ** M) * (2 ** N)
    vec = np.asarray(state.data if hasattr(state, "data") else state, dtype=complex)

    if vec.ndim != 1:
        raise ValueError("Input state must be a 1-D vector.")
    if vec.size != expected_dim:
        raise ValueError(
            f"Dimension mismatch: got {vec.size}, expected {expected_dim}"
        )

    v0, v1 = five_qubit_logical_basis()

    # Native-qudit tensors use C order, unlike the Qiskit binary embedding.
    encoding = np.column_stack([v0, v1]).reshape((2,) * 6)
    state_tensor = vec.reshape((d,) * M + (2,) * N)

    for receiver in range(N):
        axis = M + 5 * receiver
        previous_ndim = state_tensor.ndim
        state_tensor = np.tensordot(encoding, state_tensor, axes=([5], [axis]))
        # Return the five physical axes to the logical receiver's position.
        permutation = (
            list(range(5, 5 + axis))
            + list(range(5))
            + list(range(5 + axis, previous_ndim + 4))
        )
        state_tensor = np.transpose(state_tensor, permutation)

    encoded_vec = state_tensor.reshape(-1)
    expected_encoded_dim = (d ** M) * (2 ** (5 * N))
    if encoded_vec.size != expected_encoded_dim:
        raise RuntimeError(
            f"Encoded dimension mismatch: {encoded_vec.size} vs {expected_encoded_dim}"
        )
    return Statevector(encoded_vec)


# ---------------------------------------------------------------------------
# Depolarizing noise for encoded states (exact + sampling)
# ---------------------------------------------------------------------------

def depolarizing_channels_encoded(
    M: int,
    N: int,
    state: Statevector,
    p_list: list[float],
    *,
    mode: str = "exact",
    exact_dim_max: int = 5_000,
    n_samples: int = 200,
    seed: int | None = None,
    return_density_estimate: bool = False,
) -> dict[str, Any]:
    """Depolarizing noise on [[5,1,3]]-encoded receiver blocks.

    ``"exact"`` uses a full density matrix and ``"sampling"`` uses Pauli
    trajectories. Any other mode selects between them using *exact_dim_max*.

    Parameters
    ----------
    M : int
        Number of sender qudits.
    N : int
        Number of receivers (logical blocks).
    state : Statevector or np.ndarray
        Encoded pure state, dimension :math:`(N+1)^M \times 2^{5N}`.
    p_list : list[float]
        Depolarizing probability per receiver block (applied to each of
        its 5 physical qubits independently).
    mode : str
        ``"exact"`` or ``"sampling"`` forces that mode; ``"auto"`` selects
        exact evolution when the dimension is at most *exact_dim_max*.
    exact_dim_max : int
        Automatic threshold: use exact mode when D <= this value and
        *mode* is not explicitly ``"sampling"``.
    n_samples : int
        Number of Pauli trajectories for sampling mode.
    seed : int or None
        RNG seed.
    return_density_estimate : bool
        If True (sampling mode only), also return the empirical density
        matrix.

    Returns
    -------
    dict
        ``{"mode": "exact", "rho": ndarray, "D": int}`` or
        ``{"mode": "sampled", "trajectories": list[ndarray], ...}``.
    """
    rng = np.random.default_rng(seed)

    d_qudit = N + 1
    D = (d_qudit ** M) * (2 ** (5 * N))

    psi0 = np.asarray(
        state.data if hasattr(state, "data") else state, dtype=complex
    )
    if psi0.ndim != 1 or psi0.size != D:
        raise ValueError(
            f"State dimension mismatch: got {psi0.size}, expected {D}."
        )

    dims = [d_qudit] * M + [2] * (5 * N)

    X = Pauli("X").to_matrix()
    Y = Pauli("Y").to_matrix()
    Z = Pauli("Z").to_matrix()

    # --- exact ---
    use_exact = mode == "exact" or (mode != "sampling" and D <= exact_dim_max)
    if use_exact:
        rho_out = np.outer(psi0, psi0.conj())
        for i, p in enumerate(p_list):
            for t in range(5):
                ax = M + 5 * i + t
                rho_tensor = rho_out.reshape(dims + dims)
                XrX = _apply_density_operator(rho_tensor, X, ax)
                YrY = _apply_density_operator(rho_tensor, Y, ax)
                ZrZ = _apply_density_operator(rho_tensor, Z, ax)
                rho_tensor = (1 - p) * rho_tensor + (p / 3) * (XrX + YrY + ZrZ)
                rho_out = rho_tensor.reshape(D, D)
        return {"mode": "exact", "rho": rho_out, "D": D}

    # --- sampling ---
    trajectories: list[np.ndarray] = []
    # Per-trajectory, per-block 5-letter Pauli-frame label (e.g. "IXIII"), so that
    # recovery can look up the induced syndrome directly instead of re-deriving it
    # from the state (see qec_recover_and_decode).
    pauli_labels: list[list[str]] = []
    rho_est = np.zeros((D, D), dtype=complex) if return_density_estimate else None
    pauli_ops: list[np.ndarray | None] = [None, X, Y, Z]
    pauli_letters = "IXYZ"

    for _ in range(n_samples):
        psi = psi0.copy()
        traj_labels: list[str] = []
        for i, p in enumerate(p_list):
            probs = np.array([1 - p, p / 3, p / 3, p / 3], dtype=float)
            block_letters: list[str] = []
            for t in range(5):
                ax = M + 5 * i + t
                choice = rng.choice(4, p=probs)
                block_letters.append(pauli_letters[choice])
                if choice != 0:
                    psi = _apply_state_operator(
                        psi.reshape(dims), pauli_ops[choice], ax
                    ).reshape(-1)
            traj_labels.append("".join(block_letters))
        trajectories.append(psi)
        pauli_labels.append(traj_labels)
        if return_density_estimate:
            rho_est += np.outer(psi, psi.conj())

    out: dict[str, Any] = {
        "mode": "sampled",
        "trajectories": trajectories,
        "pauli_labels": pauli_labels,
        "D": D,
        "n_samples": n_samples,
    }
    if return_density_estimate:
        out["rho_est"] = rho_est / n_samples
    return out


# ---------------------------------------------------------------------------
# QEC recovery + decode
# ---------------------------------------------------------------------------

def five_qubit_recovery_kraus_operators() -> tuple[
    dict[str, np.ndarray], np.ndarray, np.ndarray
]:
    r"""Build the ideal [[5,1,3]] recovery-and-decode Kraus operators, by syndrome.

    For syndrome *s* with Pauli representative :math:`E_s` and codespace projector
    :math:`P_{\mathcal C}`, the correct recovery-decode map is
    :math:`K_s = V_{\mathrm{Dec}} E_s^\dagger P_s`, where
    :math:`P_s = E_s P_{\mathcal C} E_s^\dagger` projects onto syndrome sector *s*.
    Because the Pauli representatives are Hermitian and involutory
    (:math:`E_s^\dagger = E_s`, :math:`E_s^2 = I`), this simplifies to
    :math:`K_s = V_{\mathrm{Dec}} P_{\mathcal C} E_s`, which is exactly what is
    computed below (``V_dec @ E_s @ Pi_s`` reduces to ``V_dec @ P_code @ E_s``).

    Returns
    -------
    dict[str, np.ndarray]
        Mapping from 4-bit syndrome string (e.g. ``"0000"``) to the corresponding
        ``2 x 32`` recovery-decode Kraus operator.
    np.ndarray
        ``|0_L>``.
    np.ndarray
        ``|1_L>``.
    """
    v0, v1 = five_qubit_logical_basis()
    P_code = np.outer(v0, v0.conj()) + np.outer(v1, v1.conj())
    V_dec = np.vstack([v0.conj(), v1.conj()])

    reps: dict[str, np.ndarray] = {"0000": np.eye(32, dtype=complex)}
    for q in range(5):
        for letter in ("X", "Y", "Z"):
            letters = ["I"] * 5
            letters[q] = letter
            label = "".join(letters)
            reps[pauli_label_syndrome(label)] = Pauli(label).to_matrix()

    K_by_syndrome: dict[str, np.ndarray] = {}
    for s, E_s in reps.items():
        Pi_s = E_s @ P_code @ E_s
        K_by_syndrome[s] = V_dec @ E_s @ Pi_s

    return K_by_syndrome, v0, v1


def logical_error_polynomial(p: float) -> float:
    r"""Exact closed-form [[5,1,3]] logical error probability.

    For ideal syndrome recovery under independent single-qubit depolarizing noise
    of strength *p* per physical qubit, direct enumeration of the weight
    distribution of the 4**5 Pauli patterns gives

    .. math::
        p_L(p) = 10p^2 - \frac{200}{9}p^3 + \frac{160}{9}p^4 - \frac{128}{27}p^5,

    with corresponding fidelity :math:`F_{\mathrm{QEC}}(p) = 1 - \tfrac{2}{3}p_L(p)`
    and low-noise break-even point
    :math:`p_\star = (3-\sqrt6)/4 \approx 0.1376`. The physical probability of
    two or more errors alone does not determine the logical channel: some
    higher-weight patterns have trivial residual logical action.
    """
    return 10 * p**2 - (200 / 9) * p**3 + (160 / 9) * p**4 - (128 / 27) * p**5


def logical_error_probability_bruteforce(p: float) -> float:
    """Exact [[5,1,3]] logical error probability via brute-force enumeration.

    Checks :func:`logical_error_polynomial` without using the closed-form expression,
    but shares the production recovery Kraus and syndrome helpers. The separate
    binary-symplectic oracle in ``tests/test_qec_recovery.py`` provides independent
    validation of the logical weight distribution. In this helper,
    every one of the ``4**5 = 1024`` five-qubit Pauli error patterns is applied
    directly to both logical basis states, recovered via the syndrome-indexed
    Kraus operator, and checked for whether the residual action on the code space
    is proportional to the identity (no logical error) or not (logical X/Y/Z).
    """
    K_by_syndrome, v0, v1 = five_qubit_recovery_kraus_operators()
    letters = "IXYZ"

    total = 0.0
    for combo in itertools.product(range(4), repeat=5):
        label = "".join(letters[c] for c in combo)
        n_err = sum(1 for c in combo if c != 0)
        weight = (1 - p) ** (5 - n_err) * (p / 3) ** n_err
        if weight == 0.0:
            continue

        E_actual = Pauli(label).to_matrix()

        K = K_by_syndrome[pauli_label_syndrome(label)]
        recovered = np.column_stack([K @ (E_actual @ v0), K @ (E_actual @ v1)])

        no_logical_error = (
            abs(recovered[0, 1]) < 1e-6
            and abs(recovered[1, 0]) < 1e-6
            and abs(recovered[0, 0] - recovered[1, 1]) < 1e-6
        )
        if not no_logical_error:
            total += weight
    return total


def qec_recover_and_decode(
    hybrid_result: dict[str, Any],
    M: int,
    N: int,
    tol: float = 1e-10,
) -> DensityMatrix:
    """Apply ideal [[5,1,3]] recovery and decode on each receiver block.

    Accepts the output of :func:`depolarizing_channels_encoded` and
    returns a density matrix on the reduced space
    :math:`(N+1)^M \\times 2^N`.

    For ``mode == "sampled"`` trajectories that carry a ``"pauli_labels"`` entry
    (as produced by :func:`depolarizing_channels_encoded`), the syndrome for each
    block is computed directly from the actually-sampled Pauli error via
    :func:`pauli_label_syndrome`, and the matching recovery Kraus operator is
    applied deterministically -- no search over syndrome branches is needed. If
    ``"pauli_labels"`` is absent (e.g. legacy physical-Pauli trajectories), recovery
    emits a warning and verifies that exactly one syndrome carries all of the
    state's norm. Inputs occupying multiple syndrome branches are rejected rather
    than projected onto their most likely branch; use exact density-matrix
    recovery for such coherent inputs.

    Parameters
    ----------
    hybrid_result : dict
        Output of :func:`depolarizing_channels_encoded`.
    M : int
        Number of sender qudits.
    N : int
        Number of receivers.
    tol : float
        Probability threshold for syndrome branch selection.

    Returns
    -------
    DensityMatrix
    """
    d_qudit = N + 1

    K_by_syndrome, _v0, _v1 = five_qubit_recovery_kraus_operators()
    K_local = [K_by_syndrome[s] for s in sorted(K_by_syndrome)]

    # --- tensor helpers ---
    def _kraus_density(
        rho_mat: np.ndarray,
        dims_cur: list[int],
        ax: int,
        K_list: list[np.ndarray],
    ) -> tuple[np.ndarray, list[int]]:
        rho_tensor = rho_mat.reshape(dims_cur + dims_cur)
        acc = None
        for K in K_list:
            branch = _apply_density_operator(rho_tensor, K, ax)
            acc = branch if acc is None else acc + branch
        dims_new = dims_cur[:ax] + [2] + dims_cur[ax + 1 :]
        return acc.reshape(int(np.prod(dims_new)), int(np.prod(dims_new))), dims_new

    def _kraus_state_by_label(
        psi_vec: np.ndarray,
        dims_cur: list[int],
        ax: int,
        label: str,
        tol_inner: float,
    ) -> tuple[np.ndarray, list[int]]:
        K = K_by_syndrome[pauli_label_syndrome(label)]
        vec = _apply_state_operator(psi_vec.reshape(dims_cur), K, ax).reshape(-1)
        p_branch = float(np.vdot(vec, vec).real)
        if p_branch < tol_inner:
            raise RuntimeError(
                f"Recovery branch for the sampled Pauli frame {label!r} has ~zero "
                "probability; the tracked Pauli label may be inconsistent with the "
                "trajectory."
            )
        norm_sq = float(np.vdot(psi_vec, psi_vec).real)
        if not np.isclose(p_branch, norm_sq, rtol=tol_inner, atol=tol_inner):
            raise ValueError(
                "Trajectory is not confined to its tracked Pauli syndrome; "
                "use exact density-matrix recovery for coherent noise."
            )
        dims_new = dims_cur[:ax] + [2] + dims_cur[ax + 1 :]
        return vec / np.sqrt(p_branch), dims_new

    def _kraus_state_single_syndrome(
        psi_vec: np.ndarray,
        dims_cur: list[int],
        ax: int,
        K_list: list[np.ndarray],
        tol_inner: float,
    ) -> tuple[np.ndarray, list[int]]:
        psi_tensor = psi_vec.reshape(dims_cur)
        best_vec = None
        best_p = -1.0
        for K in K_list:
            vec = _apply_state_operator(psi_tensor, K, ax).reshape(-1)
            p_branch = float(np.vdot(vec, vec).real)
            if p_branch > best_p:
                best_p = p_branch
                best_vec = vec
        if best_p < tol_inner:
            raise RuntimeError("All syndrome branch probabilities ~ 0.")
        norm_sq = float(np.vdot(psi_vec, psi_vec).real)
        if not np.isclose(best_p, norm_sq, rtol=tol_inner, atol=tol_inner):
            raise ValueError(
                "Unlabeled trajectory occupies multiple syndrome branches; "
                "use exact density-matrix recovery for coherent noise."
            )
        dims_new = dims_cur[:ax] + [2] + dims_cur[ax + 1 :]
        return best_vec / np.sqrt(best_p), dims_new

    # --- apply ---
    dims_in = [d_qudit] * M + [2] * (5 * N)
    dims_out = [d_qudit] * M + [2] * N
    D_out = int(np.prod(dims_out))
    run_mode = hybrid_result["mode"]

    if run_mode == "exact":
        rho = np.asarray(hybrid_result["rho"], dtype=complex)
        dims_cur = dims_in[:]
        for ell in range(N):
            ax = M + ell
            dims_fused = dims_cur[:ax] + [32] + dims_cur[ax + 5 :]
            rho, dims_cur = _kraus_density(rho, dims_fused, ax, K_local)
        return DensityMatrix(rho)

    # sampled
    trajs = hybrid_result["trajectories"]
    pauli_labels = hybrid_result.get("pauli_labels")
    if pauli_labels is None:
        warnings.warn(
            "depolarizing_channels_encoded output has no 'pauli_labels'; falling "
            "back to validated single-syndrome recovery. Coherent trajectories "
            "occupying multiple syndrome branches are rejected.",
            RuntimeWarning,
            stacklevel=2,
        )

    rho_est = np.zeros((D_out, D_out), dtype=complex)
    for idx, psi in enumerate(trajs):
        psi = np.asarray(psi, dtype=complex)
        dims_cur = dims_in[:]
        for ell in range(N):
            ax = M + ell
            dims_fused = dims_cur[:ax] + [32] + dims_cur[ax + 5 :]
            if pauli_labels is not None:
                psi, dims_cur = _kraus_state_by_label(
                    psi, dims_fused, ax, pauli_labels[idx][ell], tol
                )
            else:
                psi, dims_cur = _kraus_state_single_syndrome(
                    psi, dims_fused, ax, K_local, tol
                )
        rho_est += np.outer(psi, psi.conj())
    return DensityMatrix(rho_est / len(trajs))


# ---------------------------------------------------------------------------
# High-level orchestrators
# ---------------------------------------------------------------------------


def _measure_and_score_receivers(
    rho: DensityMatrix,
    M: int,
    N: int,
    alpha: float,
    theta_list: list[float],
    outcomes_list: list[int] | None,
    seed: int | None,
) -> tuple[list[float], Statevector, list[DensityMatrix]]:
    """Complete sender control and score the bare or decoded receiver states."""
    rho = apply_alice_unitaries(M, N, rho, theta_list)
    rho, outcomes = measure_alices(M, N, rho, outcomes_list, seed=seed)
    rho = apply_corrections(M, N, rho, outcomes)

    dims = ((N + 1) ** M,) + (2,) * N
    reduced_states = [
        DensityMatrix(partial_trace_np(rho, dims, [i + 1]))
        for i in range(N)
    ]

    beta = np.sqrt(1 - alpha ** 2)
    theta_total = np.sum(theta_list)
    target_state = Statevector(
        [alpha * np.exp(1j * theta_total), beta * np.exp(-1j * theta_total)]
    )
    target_density = DensityMatrix(target_state)
    fidelities = [state_fidelity(state, target_density) for state in reduced_states]
    return fidelities, target_state, reduced_states


def run_broadcast_no_qec(
    M: int,
    N: int,
    alpha: float,
    theta_list: list[float],
    p_list: list[float],
    outcomes_list: list[int] | None = None,
    seed: int | None = None,
) -> tuple[list[float], Statevector, list[DensityMatrix]]:
    """Run bare broadcasting; return fidelities, target, and receiver states.

    ``p_list`` contains one depolarizing probability per receiver.
    """
    rho = DensityMatrix(get_initial_state(M=M, N=N, alpha=alpha))
    rho = depolarizing_channels(M, N, rho, p_list)
    return _measure_and_score_receivers(
        rho, M, N, alpha, theta_list, outcomes_list, seed
    )


def run_broadcast_qec(
    M: int,
    N: int,
    alpha: float,
    theta_list: list[float],
    p_list: list[float],
    outcomes_list: list[int] | None = None,
    *,
    mode: str = "exact",
    n_samples: int = 200,
    seed: int | None = None,
) -> tuple[list[float], Statevector, list[DensityMatrix]]:
    """Full broadcasting pipeline *with* [[5,1,3]] QEC.

    Parameters
    ----------
    mode : ``"exact"`` or ``"sampling"``
        Simulation strategy for the depolarizing channel.

    Returns
    -------
    fidelities : list[float]
    target_state : Statevector
    reduced_states : list[DensityMatrix]
    """
    psi = get_initial_state(M=M, N=N, alpha=alpha)
    encoded = encode_initial_state(psi, M=M, N=N)

    noisy = depolarizing_channels_encoded(
        M, N, encoded, p_list, mode=mode, n_samples=n_samples, seed=seed,
    )
    rho = qec_recover_and_decode(noisy, M=M, N=N)
    return _measure_and_score_receivers(
        rho, M, N, alpha, theta_list, outcomes_list, seed
    )
