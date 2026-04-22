"""Local simulation of the M-sender, N-receiver broadcasting protocol.

Provides exact density-matrix and Monte Carlo Pauli-trajectory simulation
paths, with optional [[5,1,3]] quantum error correction.  All functions
operate on native qudit dimensions (dim = N+1 per sender) — no binary
qubit encoding is needed.
"""

import itertools
from math import comb
from typing import Any

import numpy as np
from qiskit.quantum_info import DensityMatrix, Pauli, Statevector, state_fidelity


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
    alpha: float = 1 / np.sqrt(2),
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
    alpha : float
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

    def qudit_index(k: int) -> int:
        idx = 0
        for _ in range(M):
            idx = idx * d_qudit + k
        return idx

    def qubit_index(bitstring: list[int]) -> int:
        idx = 0
        for b in bitstring:
            idx = (idx << 1) | b
        return idx

    for k in range(N + 1):
        coeff = (alpha ** k) * (beta ** (N - k)) * np.sqrt(comb(N, k))
        qd_idx = qudit_index(k)

        for zeros in itertools.combinations(range(N), k):
            bits = [1] * N
            for z in zeros:
                bits[z] = 0
            qb_idx = qubit_index(bits)
            state[qd_idx * dim_qubits + qb_idx] += coeff / np.sqrt(comb(N, k))

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

def _five_qubit_logical_basis() -> tuple[np.ndarray, np.ndarray]:
    """Return ``(|0_L>, |1_L>)`` for the [[5,1,3]] code (big-endian)."""

    def bits_to_index(bitstr: str) -> int:
        idx = 0
        for ch in bitstr:
            idx = (idx << 1) | int(ch)
        return idx

    v0 = np.zeros(32, dtype=complex)
    for s in ("00000", "10010", "01001", "10100", "01010", "00101"):
        v0[bits_to_index(s)] += 0.25
    for s in (
        "11011", "00110", "11000", "11101", "00011",
        "11110", "01111", "10001", "01100", "10111",
    ):
        v0[bits_to_index(s)] -= 0.25

    v1 = np.zeros(32, dtype=complex)
    for idx, amp in enumerate(v0):
        if amp != 0:
            v1[idx ^ 0b11111] = amp

    return v0, v1


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

    v0, v1 = _five_qubit_logical_basis()

    # Encoding isometry tensor  E[b1,b2,b3,b4,b5, q]
    E = np.zeros((2, 2, 2, 2, 2, 2), dtype=complex)
    E[..., 0] = v0.reshape(2, 2, 2, 2, 2)
    E[..., 1] = v1.reshape(2, 2, 2, 2, 2)

    psi = vec.reshape((d,) * M + (2,) * N)

    for ell in range(N):
        ax = M + 5 * ell
        R = psi.ndim
        psi = np.tensordot(E, psi, axes=([5], [ax]))
        perm = (
            list(range(5, 5 + ax))
            + list(range(0, 5))
            + list(range(5 + ax, 5 + (R - 1)))
        )
        psi = np.transpose(psi, perm)

    encoded_vec = psi.reshape(-1)
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

    For small Hilbert spaces (D <= *exact_dim_max*) or when *mode* is
    ``"exact"``, the channel is applied via full density-matrix evolution.
    Otherwise Monte Carlo Pauli trajectories are sampled.

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
    mode : ``"exact"`` or ``"sampling"``
        Force a specific simulation mode.  When ``"exact"`` the full
        density matrix is used regardless of dimension.
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
    L = len(dims)

    X = Pauli("X").to_matrix().astype(complex)
    Y = Pauli("Y").to_matrix().astype(complex)
    Z = Pauli("Z").to_matrix().astype(complex)

    # --- helpers ---
    def _apply_unitary_on_subsystem(vec: np.ndarray, U: np.ndarray, ax: int) -> np.ndarray:
        psi = vec.reshape(dims)
        tmp = np.tensordot(U, psi, axes=([1], [ax]))
        tmp = np.moveaxis(tmp, 0, ax)
        return tmp.reshape(-1)

    def _conjugate_density(rho_tensor: np.ndarray, U: np.ndarray, ax: int) -> np.ndarray:
        tmp = np.tensordot(U, rho_tensor, axes=([1], [ax]))
        tmp = np.moveaxis(tmp, 0, ax)
        bra_ax = L + ax
        tmp2 = np.tensordot(tmp, U.conj().T, axes=([bra_ax], [0]))
        return np.moveaxis(tmp2, -1, bra_ax)

    # --- exact ---
    use_exact = mode == "exact" or (mode != "sampling" and D <= exact_dim_max)
    if use_exact:
        rho_out = np.outer(psi0, psi0.conj())
        for i, p in enumerate(p_list):
            for t in range(5):
                ax = M + 5 * i + t
                rho_tensor = rho_out.reshape(dims + dims)
                XrX = _conjugate_density(rho_tensor, X, ax)
                YrY = _conjugate_density(rho_tensor, Y, ax)
                ZrZ = _conjugate_density(rho_tensor, Z, ax)
                rho_tensor = (1 - p) * rho_tensor + (p / 3) * (XrX + YrY + ZrZ)
                rho_out = rho_tensor.reshape(D, D)
        return {"mode": "exact", "rho": rho_out, "D": D}

    # --- sampling ---
    trajectories: list[np.ndarray] = []
    rho_est = np.zeros((D, D), dtype=complex) if return_density_estimate else None
    pauli_ops: list[np.ndarray | None] = [None, X, Y, Z]

    for _ in range(n_samples):
        psi = psi0.copy()
        for i, p in enumerate(p_list):
            probs = np.array([1 - p, p / 3, p / 3, p / 3], dtype=float)
            for t in range(5):
                ax = M + 5 * i + t
                choice = rng.choice(4, p=probs)
                if choice != 0:
                    psi = _apply_unitary_on_subsystem(psi, pauli_ops[choice], ax)
        trajectories.append(psi)
        if return_density_estimate:
            rho_est += np.outer(psi, psi.conj())

    out: dict[str, Any] = {
        "mode": "sampled",
        "trajectories": trajectories,
        "D": D,
        "n_samples": n_samples,
    }
    if return_density_estimate:
        out["rho_est"] = rho_est / n_samples
    return out


# ---------------------------------------------------------------------------
# QEC recovery + decode
# ---------------------------------------------------------------------------

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

    I2 = np.eye(2, dtype=complex)
    X = np.array([[0, 1], [1, 0]], dtype=complex)
    Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    Z = np.array([[1, 0], [0, -1]], dtype=complex)
    pauli_dict = {"I": I2, "X": X, "Y": Y, "Z": Z}

    def _kron_all(mats: list[np.ndarray]) -> np.ndarray:
        out = mats[0]
        for m in mats[1:]:
            out = np.kron(out, m)
        return out

    v0, v1 = _five_qubit_logical_basis()
    P_code = np.outer(v0, v0.conj()) + np.outer(v1, v1.conj())
    V_dec = np.vstack([v0.conj(), v1.conj()])

    g_labels = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]
    G = [_kron_all([pauli_dict[c] for c in lbl]) for lbl in g_labels]

    def _syndrome(E: np.ndarray) -> str:
        bits = []
        for g in G:
            if np.linalg.norm(E @ g - g @ E) < 1e-8:
                bits.append("0")
            elif np.linalg.norm(E @ g + g @ E) < 1e-8:
                bits.append("1")
            else:
                raise RuntimeError("Syndrome detection failed.")
        return "".join(bits)

    reps: dict[str, np.ndarray] = {"0000": np.eye(32, dtype=complex)}
    for q in range(5):
        for P1 in (X, Y, Z):
            mats = [I2] * 5
            mats[q] = P1
            E = _kron_all(mats)
            reps[_syndrome(E)] = E

    K_local = []
    for s in sorted(reps.keys()):
        E_s = reps[s]
        Pi_s = E_s @ P_code @ E_s
        K_local.append(V_dec @ E_s @ Pi_s)

    # --- tensor helpers ---
    def _kraus_density(
        rho_mat: np.ndarray,
        dims_cur: list[int],
        ax: int,
        K_list: list[np.ndarray],
    ) -> tuple[np.ndarray, list[int]]:
        L_cur = len(dims_cur)
        rho_tensor = rho_mat.reshape(dims_cur + dims_cur)
        acc = None
        for K in K_list:
            tmp = np.tensordot(K, rho_tensor, axes=([1], [ax]))
            tmp = np.moveaxis(tmp, 0, ax)
            bra_ax = L_cur + ax
            tmp2 = np.tensordot(tmp, K.conj().T, axes=([bra_ax], [0]))
            tmp2 = np.moveaxis(tmp2, -1, bra_ax)
            acc = tmp2 if acc is None else (acc + tmp2)
        dims_new = dims_cur[:ax] + [2] + dims_cur[ax + 1 :]
        return acc.reshape(int(np.prod(dims_new)), int(np.prod(dims_new))), dims_new

    def _kraus_state(
        psi_vec: np.ndarray,
        dims_cur: list[int],
        ax: int,
        K_list: list[np.ndarray],
        tol_inner: float = 1e-10,
    ) -> tuple[np.ndarray, list[int]]:
        psi_tensor = psi_vec.reshape(dims_cur)
        best_vec = None
        best_p = -1.0
        for K in K_list:
            tmp = np.tensordot(K, psi_tensor, axes=([1], [ax]))
            tmp = np.moveaxis(tmp, 0, ax)
            vec = tmp.reshape(-1)
            p = float(np.vdot(vec, vec).real)
            if p > best_p:
                best_p = p
                best_vec = vec
        if best_p < tol_inner:
            raise RuntimeError("All syndrome branch probabilities ~ 0.")
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
            D_fused = int(np.prod(dims_fused))
            rho = rho.reshape(dims_cur + dims_cur)
            rho = rho.reshape(dims_fused + dims_fused)
            rho = rho.reshape(D_fused, D_fused)
            rho, dims_cur = _kraus_density(rho, dims_fused, ax, K_local)
        return DensityMatrix(rho)

    # sampled
    trajs = hybrid_result["trajectories"]
    rho_est = np.zeros((D_out, D_out), dtype=complex)
    for psi in trajs:
        psi = np.asarray(psi, dtype=complex)
        dims_cur = dims_in[:]
        for ell in range(N):
            ax = M + ell
            dims_fused = dims_cur[:ax] + [32] + dims_cur[ax + 5 :]
            psi = psi.reshape(dims_cur).reshape(dims_fused).reshape(-1)
            psi, dims_cur = _kraus_state(psi, dims_fused, ax, K_local, tol)
        rho_est += np.outer(psi, psi.conj())
    return DensityMatrix(rho_est / len(trajs))


# ---------------------------------------------------------------------------
# High-level orchestrators
# ---------------------------------------------------------------------------

def run_broadcast_no_qec(
    M: int,
    N: int,
    alpha: float,
    theta_list: list[float],
    p_list: list[float],
    outcomes_list: list[int] | None = None,
    seed: int | None = None,
) -> tuple[list[float], Statevector, list[DensityMatrix]]:
    """Full broadcasting pipeline *without* QEC.

    Returns
    -------
    fidelities : list[float]
    target_state : Statevector
    reduced_states : list[DensityMatrix]
    """
    rho = DensityMatrix(get_initial_state(M=M, N=N, alpha=alpha))
    rho = depolarizing_channels(M, N, rho, p_list)
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
    fidelities = [
        state_fidelity(rs, DensityMatrix(target_state)) for rs in reduced_states
    ]
    return fidelities, target_state, reduced_states


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
    fidelities = [
        state_fidelity(rs, DensityMatrix(target_state)) for rs in reduced_states
    ]
    return fidelities, target_state, reduced_states
