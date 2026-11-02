"""Minimal ULID: a lexicographically sortable id.

#0313 chose ULID over a plain uuid deliberately - event ids are the tiebreak
when two events share a timestamp, and because a checkpoint RESETS the running
total, mis-ordering does not merely reorder history, it silently changes
on_hand. A uuid4 tiebreak is random; a ULID sorts chronologically for free.
"""

from __future__ import annotations

import os
import time

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford, no I/L/O/U


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_B32[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_ulid(timestamp_ms: int | None = None) -> str:
    """26 chars: 10 of millisecond timestamp, 16 of randomness."""
    ms = int(time.time() * 1000) if timestamp_ms is None else int(timestamp_ms)
    return _encode(ms, 10) + _encode(int.from_bytes(os.urandom(10), "big"), 16)
