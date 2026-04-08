"""Shared fixtures for broadcasting protocol tests."""

import numpy as np
import pytest


@pytest.fixture
def alpha():
    """Default alpha parameter (equal superposition)."""
    return 1 / np.sqrt(2)


@pytest.fixture
def stabilizer_matrices():
    """Return the four [[5,1,3]] stabilizer generators as 32x32 matrices."""
    I2 = np.eye(2, dtype=complex)
    X = np.array([[0, 1], [1, 0]], dtype=complex)
    Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    Z = np.array([[1, 0], [0, -1]], dtype=complex)
    pauli_map = {"I": I2, "X": X, "Y": Y, "Z": Z}

    labels = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"]

    def kron_all(mats):
        out = mats[0]
        for m in mats[1:]:
            out = np.kron(out, m)
        return out

    return [kron_all([pauli_map[c] for c in lbl]) for lbl in labels]
