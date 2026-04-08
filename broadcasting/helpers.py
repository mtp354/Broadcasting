"""Utility functions for sender qubit encoding."""

from math import ceil, log2


def sender_encoding_qubits(N: int) -> int:
    """Number of qubits needed to embed one (N+1)-level sender qudit."""
    return int(ceil(log2(N + 1)))


def packed_sender_value(outcomes, nq):
    """Pack sender outcomes into a single little-endian classical integer."""
    packed = 0
    for j, outcome in enumerate(outcomes):
        for bit in range(nq):
            packed |= ((outcome >> bit) & 1) << (j * nq + bit)
    return packed
