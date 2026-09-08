"""Validate the linear (bit-conditional) feedforward against the original
exponential-branch feedforward, using the standard qc.initialize-based prep.
"""

import numpy as np
import pytest

import broadcasting as db

aer = pytest.importorskip("qiskit_aer")
from qiskit_aer import AerSimulator


class TestLinearFeedforward:
    """linear_feedforward=True must reproduce linear_feedforward=False's fidelity
    for every valid sender outcome."""

    @pytest.mark.parametrize("M,N,thetas", [
        (1, 1, [0.3]),
        (1, 2, [0.7]),
        (2, 2, [0.3, 1.1]),
    ])
    def test_matches_exponential_feedforward(self, M, N, thetas):
        def run(linear):
            qc = db.generate_qiskit_circuit(
                M, N, thetas, alphas=1 / np.sqrt(2), tau=0,
                linear_feedforward=linear,
            )
            qc, reg_name, _ = db.add_fidelity(qc, N=N, thetas=thetas)
            sim = AerSimulator(method="automatic")
            result = sim.run(qc, shots=8192, seed_simulator=0).result()
            counts = result.get_counts()
            total = sum(counts.values())
            fids = []
            for i in range(N):
                p0 = sum(
                    c for bs, c in counts.items()
                    if bs.split()[0][N - 1 - i] == "0"
                )
                fids.append(p0 / total)
            return fids

        fid_linear = run(True)
        fid_exp = run(False)
        for a, b in zip(fid_linear, fid_exp):
            assert a == pytest.approx(b, abs=0.03)
