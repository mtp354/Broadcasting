"""Tests validating the [[5,1,3]] recovery-and-decode map in broadcasting.simulation.

These correspond to the critique's Eq. (36) / Eq. (32)-(33) findings: the exact
recovery formula ``K_s = V_Dec E_s^dagger P_s`` must (1) correct every weight-one
Pauli error exactly, (2) be trace preserving, (3) induce a logical channel matching
the exact closed-form polynomial p_L(p), and (4) give unit fidelity for the
noiseless encoded protocol.
"""

import itertools
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

    def test_full_depolarization_anti_contraction_values(self):
        """At p=1 (complete depolarization), p_L(1) = 22/27 and F_QEC(1) = 37/81."""
        assert logical_error_polynomial(1.0) == pytest.approx(22 / 27, abs=1e-9)
        assert 1 - (2 / 3) * logical_error_polynomial(1.0) == pytest.approx(37 / 81, abs=1e-9)

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


class TestIndependentSymplecticOracle:
    """Genuinely independent oracle for [[5,1,3]] logical error evaluation.

    Constructed strictly from first principles via binary symplectic linear algebra
    over GF(2), with NO imports or calls to production recovery helpers
    (five_qubit_recovery_kraus_operators, pauli_label_syndrome).
    """

    @staticmethod
    def _generators():
        return [
            ([1, 0, 0, 1, 0], [0, 1, 1, 0, 0]),  # XZZXI
            ([0, 1, 0, 0, 1], [0, 0, 1, 1, 0]),  # IXZZX
            ([1, 0, 1, 0, 0], [0, 0, 0, 1, 1]),  # XIXZZ
            ([0, 1, 0, 1, 0], [1, 0, 0, 0, 1]),  # ZXIXZ
        ]

    @staticmethod
    def _logicals():
        log_X = ([1, 1, 1, 1, 1], [0, 0, 0, 0, 0])
        log_Z = ([0, 0, 0, 0, 0], [1, 1, 1, 1, 1])
        return log_X, log_Z

    @staticmethod
    def _symp_inner(p1, p2):
        return sum(x1 * z2 + z1 * x2 for x1, z1, x2, z2 in zip(p1[0], p1[1], p2[0], p2[1])) % 2

    def _syndrome(self, p):
        return tuple(self._symp_inner(p, g) for g in self._generators())

    def _build_recovery_lookup(self):
        rec_lookup = {}
        # Weight 0
        p0 = ([0] * 5, [0] * 5)
        rec_lookup[self._syndrome(p0)] = p0
        # Weight 1
        for q in range(5):
            for x, z in [(1, 0), (1, 1), (0, 1)]:
                px, pz = [0] * 5, [0] * 5
                px[q] = x
                pz[q] = z
                p1 = (px, pz)
                syn = self._syndrome(p1)
                assert syn not in rec_lookup
                rec_lookup[syn] = p1
        assert len(rec_lookup) == 16
        return rec_lookup

    def test_syndrome_lookup_coverage(self):
        """The 15 weight-one Paulis plus identity must map 1-to-1 to all 16 syndromes."""
        lookup = self._build_recovery_lookup()
        assert len(lookup) == 16
        assert self._syndrome(([0] * 5, [0] * 5)) in lookup

    def test_isotropic_weight_distribution_and_polynomial(self):
        """Enumerate all 1024 Paulis and verify exact isotropic counts and polynomial match."""
        lookup = self._build_recovery_lookup()
        log_X, log_Z = self._logicals()
        pauli_letters = [(0, 0), (1, 0), (1, 1), (0, 1)]  # I, X, Y, Z

        counts = {w: {"I": 0, "X": 0, "Y": 0, "Z": 0} for w in range(6)}

        for combo in itertools.product(range(4), repeat=5):
            px = [pauli_letters[c][0] for c in combo]
            pz = [pauli_letters[c][1] for c in combo]
            weight = sum(1 for c in combo if c != 0)
            p_err = (px, pz)

            syn = self._syndrome(p_err)
            r_err = lookup[syn]

            net_x = [(x1 + x2) % 2 for x1, x2 in zip(px, r_err[0])]
            net_z = [(z1 + z2) % 2 for z1, z2 in zip(pz, r_err[1])]
            net_err = (net_x, net_z)

            cx = self._symp_inner(net_err, log_Z)
            cz = self._symp_inner(net_err, log_X)

            if cx == 0 and cz == 0:
                counts[weight]["I"] += 1
            elif cx == 1 and cz == 0:
                counts[weight]["X"] += 1
            elif cx == 0 and cz == 1:
                counts[weight]["Z"] += 1
            else:
                counts[weight]["Y"] += 1

        # Check total combinations
        assert sum(sum(counts[w].values()) for w in range(6)) == 1024

        # Weight 0: 1 total, 0 errors
        assert counts[0]["I"] == 1
        assert counts[0]["X"] == counts[0]["Y"] == counts[0]["Z"] == 0

        # Weight 1: 15 total, 0 errors
        assert counts[1]["I"] == 15
        assert counts[1]["X"] == counts[1]["Y"] == counts[1]["Z"] == 0

        # Weight 2: 90 total, 90 errors, isotropic 30/30/30
        assert counts[2]["I"] == 0
        assert counts[2]["X"] == counts[2]["Y"] == counts[2]["Z"] == 30

        # Weight 3: 270 total, 60 identity, 210 errors, isotropic 70/70/70
        assert counts[3]["I"] == 60
        assert counts[3]["X"] == counts[3]["Y"] == counts[3]["Z"] == 70

        # Weight 4: 405 total, 135 identity, 270 errors, isotropic 90/90/90
        assert counts[4]["I"] == 135
        assert counts[4]["X"] == counts[4]["Y"] == counts[4]["Z"] == 90

        # Weight 5: 243 total, 45 identity, 198 errors, isotropic 66/66/66
        assert counts[5]["I"] == 45
        assert counts[5]["X"] == counts[5]["Y"] == counts[5]["Z"] == 66

        # Cross-validate evaluated p_L against closed form logical_error_polynomial
        for p in [0.0, 0.05, 0.1, 0.1376276, 0.3, 0.5, 0.75, 1.0]:
            p_L_oracle = sum(
                (counts[w]["X"] + counts[w]["Y"] + counts[w]["Z"])
                * ((p / 3) ** w)
                * ((1 - p) ** (5 - w))
                for w in range(6)
            )
            assert p_L_oracle == pytest.approx(logical_error_polynomial(p), abs=1e-9)
