"""Utility functions for sender qubit encoding."""

from collections.abc import Iterable
from math import ceil, log2


def sender_encoding_qubits(N: int) -> int:
    """Number of qubits needed to embed one (N+1)-level sender qudit."""
    return int(ceil(log2(N + 1)))


def packed_sender_value(outcomes: Iterable[int], nq: int) -> int:
    """Pack sender outcomes into a single little-endian classical integer."""
    packed = 0
    mask = (1 << nq) - 1
    for sender, outcome in enumerate(outcomes):
        packed |= (outcome & mask) << (sender * nq)
    return packed
