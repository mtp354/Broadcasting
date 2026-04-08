"""Tests for the [[5,1,3]] quantum error correction code."""

import numpy as np
import pytest

import sys
sys.path.insert(0, "c:/Projects/Broadcasting")
import dynamic_broadcast as db


# ---------------------------------------------------------------------------
# Logical basis vectors
# ---------------------------------------------------------------------------

class TestLogicalBasis:
    """Tests for _five_qubit_logical_basis."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.v0, self.v1 = db._five_qubit_logical_basis()

    def test_normalized(self):
        assert abs(np.linalg.norm(self.v0) - 1.0) < 1e-12
        assert abs(np.linalg.norm(self.v1) - 1.0) < 1e-12

    def test_orthogonal(self):
        assert abs(np.vdot(self.v0, self.v1)) < 1e-12

    def test_in_code_space(self, stabilizer_matrices):
        """Each stabilizer must have eigenvalue +1 on both logical basis vectors."""
        for i, S in enumerate(stabilizer_matrices):
            for label, v in [("v0", self.v0), ("v1", self.v1)]:
                Sv = S @ v
                # S|v> = +1|v> means S|v> == |v>
                assert np.allclose(Sv, v, atol=1e-12), (
                    f"Stabilizer {i} eigenvalue != +1 on {label}"
                )

    def test_palindrome_symmetry(self):
        """
        The [[5,1,3]] logical basis has bit-reversal palindrome symmetry.

        This means reshape(order='C') and reshape(order='F') produce
        identical tensors for v0 and v1 — which is why the endianness
        bug was invisible when only testing the logical basis.
        """
        for v in [self.v0, self.v1]:
            for i in range(32):
                rev = int(f"{i:05b}"[::-1], 2)
                assert abs(v[i] - v[rev]) < 1e-12, (
                    f"Palindrome symmetry broken at index {i} (rev={rev})"
                )


# ---------------------------------------------------------------------------
# Decode gate
# ---------------------------------------------------------------------------

class TestDecodeGate:
    """Tests for _five_qubit_decode_gate."""

    @pytest.fixture(autouse=True)
    def setup(self):
        gate = db._five_qubit_decode_gate()
        self.U = gate.to_matrix()
        self.v0, self.v1 = db._five_qubit_logical_basis()

    def test_unitary(self):
        product = self.U @ self.U.conj().T
        assert np.allclose(product, np.eye(32), atol=1e-12)

    def test_maps_logical_zero(self):
        """U|0_L> should map to |00000> (index 0)."""
        result = self.U @ self.v0
        expected = np.zeros(32, dtype=complex)
        expected[0] = 1.0
        assert np.allclose(result, expected, atol=1e-10)

    def test_maps_logical_one(self):
        """U|1_L> should map to |00001> (index 1 in Qiskit little-endian)."""
        result = self.U @ self.v1
        expected = np.zeros(32, dtype=complex)
        expected[1] = 1.0
        assert np.allclose(result, expected, atol=1e-10)

    def test_preserves_superposition(self):
        """U(alpha|0_L> + beta|1_L>) = alpha|00000> + beta|00001>."""
        rng = np.random.default_rng(42)
        for _ in range(5):
            alpha = rng.normal() + 1j * rng.normal()
            beta = rng.normal() + 1j * rng.normal()
            norm = np.sqrt(abs(alpha) ** 2 + abs(beta) ** 2)
            alpha, beta = alpha / norm, beta / norm

            state = alpha * self.v0 + beta * self.v1
            result = self.U @ state
            expected = np.zeros(32, dtype=complex)
            expected[0] = alpha
            expected[1] = beta
            assert np.allclose(result, expected, atol=1e-10)


# ---------------------------------------------------------------------------
# Syndrome table
# ---------------------------------------------------------------------------

class TestSyndromeCorrections:
    """Tests for _five_qubit_syndrome_corrections."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.corrections = db._five_qubit_syndrome_corrections()

    def test_completeness(self):
        """Should have 16 entries (syndromes 0–15)."""
        assert len(self.corrections) == 16
        assert set(self.corrections.keys()) == set(range(16))

    def test_identity_syndrome(self):
        """Syndrome 0 maps to None (no correction needed)."""
        assert self.corrections[0] is None

    def test_unique_syndromes(self):
        """All 15 single-qubit Pauli errors produce distinct nonzero syndromes."""
        non_identity = {k: v for k, v in self.corrections.items() if v is not None}
        assert len(non_identity) == 15

    def test_error_correction_roundtrip(self, stabilizer_matrices):
        """Apply each single-qubit Pauli error, detect syndrome, correct, verify recovery."""
        I2 = np.eye(2, dtype=complex)
        X = np.array([[0, 1], [1, 0]], dtype=complex)
        Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
        Z = np.array([[1, 0], [0, -1]], dtype=complex)
        pauli_map = {"I": I2, "X": X, "Y": Y, "Z": Z}

        v0, v1 = db._five_qubit_logical_basis()

        def kron_all(mats):
            out = mats[0]
            for m in mats[1:]:
                out = np.kron(out, m)
            return out

        # Test with a superposition state
        alpha, beta = 1 / np.sqrt(3), np.sqrt(2 / 3)
        logical_state = alpha * v0 + beta * v1

        for qubit in range(5):
            for pauli_label in ("X", "Y", "Z"):
                # Apply error
                mats = [I2] * 5
                mats[qubit] = pauli_map[pauli_label]
                error_op = kron_all(mats)
                corrupted = error_op @ logical_state

                # Compute syndrome
                syndrome_bits = []
                for S in stabilizer_matrices:
                    # eigenvalue: +1 if commutes (syndrome bit 0), -1 if anticommutes (bit 1)
                    ev = np.real(np.vdot(corrupted, S @ corrupted))
                    syndrome_bits.append(0 if ev > 0 else 1)

                # Syndrome integer (little-endian to match Qiskit convention)
                syndrome_val = int("".join(str(b) for b in syndrome_bits[::-1]), 2)

                # Look up correction
                correction = self.corrections[syndrome_val]
                assert correction is not None, (
                    f"No correction for {pauli_label} on qubit {qubit} "
                    f"(syndrome={syndrome_val})"
                )
                corr_pauli, corr_qubit = correction
                assert corr_qubit == qubit
                assert corr_pauli == pauli_label

                # Apply correction
                mats_corr = [I2] * 5
                mats_corr[corr_qubit] = pauli_map[corr_pauli]
                correction_op = kron_all(mats_corr)
                recovered = correction_op @ corrupted

                # Verify recovery (up to global phase)
                fid = abs(np.vdot(logical_state, recovered)) ** 2
                assert fid > 1 - 1e-10, (
                    f"Fidelity {fid:.6f} after correcting {pauli_label} on qubit {qubit}"
                )
