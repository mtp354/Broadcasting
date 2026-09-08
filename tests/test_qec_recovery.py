"""Tests validating the [[5,1,3]] recovery-and-decode map in broadcasting.simulation.

These correspond to the critique's Eq. (36) / Eq. (32)-(33) findings: the exact
recovery formula ``K_s = V_Dec E_s^dagger P_s`` must (1) correct every weight-one
Pauli error exactly, (2) be trace preserving, (3) induce a logical channel matching
the exact closed-form polynomial p_L(p), and (4) give unit fidelity for the
noiseless encoded protocol.
"""

import numpy as np
import pytest

from broadcasting.simulation import (
    depolarizing_channels_encoded,
    encode_initial_state,
    five_qubit_recovery_kraus_operators,
    get_initial_state,
    logical_error_polynomial,
    logical_error_probability_bruteforce,
    pauli_label_syndrome,
    qec_recover_and_decode,
    run_broadcast_qec,
)


I2 = np.eye(2, dtype=complex)
PAULI = {
    "I": I2,
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
}


def _kron_all(mats):
    out = mats[0]
    for m in mats[1:]:
        out = np.kron(out, m)
    return out


def _label_matrix(label: str) -> np.ndarray:
    return _kron_all([PAULI[c] for c in label])


class TestPauliLabelSyndrome:
    """pauli_label_syndrome must agree with a direct commutator computation."""

    def test_identity_syndrome(self):
        assert pauli_label_syndrome("IIIII") == "0000"

    def test_matches_matrix_commutator(self):
        stabilizers = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]
        G = [_label_matrix(s) for s in stabilizers]
        rng = np.random.default_rng(0)
        letters = "IXYZ"
        for _ in range(30):
            label = "".join(rng.choice(list(letters), size=5))
            E = _label_matrix(label)
            bits = []
            for g in G:
                if np.allclose(E @ g, g @ E, atol=1e-8):
                    bits.append("0")
                else:
                    assert np.allclose(E @ g, -(g @ E), atol=1e-8)
                    bits.append("1")
            assert pauli_label_syndrome(label) == "".join(bits)


class TestRecoveryKrausOperators:
    """five_qubit_recovery_kraus_operators should implement V_Dec E_s^dagger P_s exactly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.K_by_syndrome, self.v0, self.v1 = five_qubit_recovery_kraus_operators()

    def test_sixteen_syndromes(self):
        assert len(self.K_by_syndrome) == 16

    def test_noiseless_decode(self):
        """Zero-error syndrome must decode |0_L>, |1_L> to |0>, |1> exactly."""
        K0 = self.K_by_syndrome["0000"]
        assert np.allclose(K0 @ self.v0, [1, 0], atol=1e-10)
        assert np.allclose(K0 @ self.v1, [0, 1], atol=1e-10)

    def test_all_weight_one_errors_corrected_exactly(self):
        """Every one of the 15 weight-one Pauli errors must decode exactly (up to a
        global phase) to the un-corrupted logical state -- this is the concrete
        check the critique requests for the corrected Eq. (36) recovery map."""
        rng = np.random.default_rng(1)
        alpha = rng.normal() + 1j * rng.normal()
        beta = rng.normal() + 1j * rng.normal()
        norm = np.hypot(abs(alpha), abs(beta))
        alpha, beta = alpha / norm, beta / norm
        logical_state = alpha * self.v0 + beta * self.v1

        for q in range(5):
            for letter in ("X", "Y", "Z"):
                letters = ["I"] * 5
                letters[q] = letter
                label = "".join(letters)
                corrupted = _label_matrix(label) @ logical_state

                syndrome = pauli_label_syndrome(label)
                assert syndrome != "0000", f"weight-one error {label} has trivial syndrome"

                recovered = self.K_by_syndrome[syndrome] @ corrupted
                recovered = recovered / np.linalg.norm(recovered)
                target = np.array([alpha, beta])
                fidelity = abs(np.vdot(target, recovered)) ** 2
                assert fidelity > 1 - 1e-8, (
                    f"Recovery failed for {letter} on qubit {q}: fidelity={fidelity:.6f}"
                )

    def test_trace_preserving(self):
        """sum_s K_s^dagger K_s must equal the identity on the full 32-dim space,
        since the 16 syndrome sectors partition it completely."""
        total = np.zeros((32, 32), dtype=complex)
        for K in self.K_by_syndrome.values():
            total += K.conj().T @ K
        assert np.allclose(total, np.eye(32), atol=1e-8)


class TestExactLogicalChannel:
    """Cross-validate the closed-form p_L(p) against independent enumeration and
    against qec_recover_and_decode's exact-mode fidelity."""

    @pytest.mark.parametrize("p", [0.0, 0.05, 0.1, 0.1376276, 0.3, 0.5, 0.75, 1.0])
    def test_bruteforce_matches_polynomial(self, p):
        assert logical_error_probability_bruteforce(p) == pytest.approx(
            logical_error_polynomial(p), abs=1e-9
        )

    def test_breakeven_point(self):
        """p_L(p) == p at p* = (3 - sqrt(6)) / 4."""
        p_star = (3 - np.sqrt(6)) / 4
        assert logical_error_polynomial(p_star) == pytest.approx(p_star, abs=1e-9)

    @pytest.mark.parametrize("p", [0.0, 0.05, 0.1376276, 0.3, 0.6])
    def test_matches_exact_density_matrix_fidelity(self, p):
        """F_QEC(p) = 1 - (2/3) p_L(p) must match the full encoded broadcasting
        pipeline's exact single-receiver fidelity (run_broadcast_qec, mode="exact"),
        independent of the closed-form polynomial and exercising the same code path
        used to produce the manuscript's QEC crossover figure."""
        M, N = 1, 2
        alpha = 1 / np.sqrt(N + 1)
        thetas = [np.pi / 4]
        fidelities, _, _ = run_broadcast_qec(
            M, N, alpha, thetas, p_list=[p] * N,
            outcomes_list=[0], mode="exact",
        )
        expected_fidelity = 1 - (2 / 3) * logical_error_polynomial(p)
        for f in fidelities:
            assert f == pytest.approx(expected_fidelity, abs=1e-6)


class TestNoiselessEncodedProtocol:
    """The noiseless encoded protocol must give fidelity 1 for arbitrary alpha, theta."""

    @pytest.mark.parametrize("seed", range(5))
    def test_random_alpha_theta(self, seed):
        rng = np.random.default_rng(seed)
        M, N = 1, 2
        alpha = float(rng.uniform(0.1, 0.9))
        theta = float(rng.uniform(0, 2 * np.pi))
        fidelities, _, _ = run_broadcast_qec(
            M, N, alpha, [theta], p_list=[0.0] * N,
            outcomes_list=[0], mode="exact",
        )
        for f in fidelities:
            assert f > 1 - 1e-8, f"Expected unit fidelity, got {f}"


class TestSampledRecoveryUsesPauliFrame:
    """qec_recover_and_decode should use the tracked Pauli frame, not an argmax
    search, whenever depolarizing_channels_encoded provides pauli_labels."""

    def test_pauli_labels_present(self):
        M, N = 1, 1
        psi = get_initial_state(M=M, N=N, alpha=1 / np.sqrt(2))
        encoded = encode_initial_state(psi, M=M, N=N)
        result = depolarizing_channels_encoded(
            M, N, encoded, [0.2], mode="sampling", n_samples=10, seed=0,
        )
        assert "pauli_labels" in result
        assert len(result["pauli_labels"]) == 10
        assert all(len(labels) == N for labels in result["pauli_labels"])
        assert all(len(label) == 5 for labels in result["pauli_labels"] for label in labels)

    def test_argmax_fallback_warns(self):
        """Stripping pauli_labels should fall back to argmax with a RuntimeWarning."""
        M, N = 1, 1
        psi = get_initial_state(M=M, N=N, alpha=1 / np.sqrt(2))
        encoded = encode_initial_state(psi, M=M, N=N)
        result = depolarizing_channels_encoded(
            M, N, encoded, [0.2], mode="sampling", n_samples=20, seed=0,
        )
        del result["pauli_labels"]
        with pytest.warns(RuntimeWarning):
            qec_recover_and_decode(result, M=M, N=N)

    def test_sampled_matches_exact_at_moderate_noise(self):
        M, N = 1, 2
        alpha = 1 / np.sqrt(N + 1)
        thetas = [np.pi / 4]
        fid_exact, _, _ = run_broadcast_qec(
            M, N, alpha, thetas, p_list=[0.3] * N,
            outcomes_list=[0], mode="exact",
        )
        fid_samp, _, _ = run_broadcast_qec(
            M, N, alpha, thetas, p_list=[0.3] * N,
            outcomes_list=[0], mode="sampling", n_samples=5000, seed=42,
        )
        for fe, fs in zip(fid_exact, fid_samp):
            assert abs(fe - fs) < 0.05
