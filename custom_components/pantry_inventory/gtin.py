"""GTIN normalisation and validation.

ONE function per concern, called from every entry point - panel, service and
websocket - so the three cannot drift (#0313). Derivation of a unit code from a
pack code is deliberately absent: #0311 established it is impossible for these
products, not merely awkward.
"""

from __future__ import annotations


def check_digit(body: str) -> int:
    """GS1 check digit for a code body (check digit not included).

    Weights alternate 3,1 aligned FROM THE RIGHT, so a 13-digit body starts on
    x3 while a 12-digit body starts on x1. Backwards, this silently validates
    the wrong codes.
    """
    total = 0
    weight = 3
    for ch in reversed(body):
        total += int(ch) * weight
        weight = 1 if weight == 3 else 3
    return (10 - (total % 10)) % 10


def is_valid_gtin(code: str) -> bool:
    if not code or not code.isdigit():
        return False
    if len(code) not in (8, 12, 13, 14):
        return False
    return int(code[-1]) == check_digit(code[:-1])


def normalise(code: str) -> str:
    """Zero-pad to 14 - the canonical stored form.

    Standard GS1 practice, NOT derivation: it makes a UPC-A and its EAN-13
    equivalent compare equal, so one physical barcode cannot become two rows.
    """
    return (code or "").strip().zfill(14)
