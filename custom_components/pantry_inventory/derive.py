"""Everything derived from the Stock Event log.

Pure functions, no Home Assistant imports, so they are directly testable.
Nothing here is ever persisted (ADR 0017).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .const import (
    CHECKPOINT_EVENTS,
    EVENT_RECONCILE,
    EVENT_STOCK_IN,
    EVENT_USE_UP,
    RATE_MIN_DAYS,
    RATE_MIN_EVENTS,
    RATE_SOURCE_ESTIMATED,
    RATE_SOURCE_MEASURED,
    RATE_WINDOW_DAYS,
    REASON_AWAITING_FIRST,
    REASON_NO_CONSUMPTION,
    REASON_NO_EVENTS,
)


def _ts(event) -> datetime:
    return datetime.fromisoformat(event.timestamp)


def in_order(events: list) -> list:
    return sorted(events, key=lambda e: (e.timestamp, e.event_id))


def signed(event) -> int:
    if event.event_type == EVENT_STOCK_IN:
        return abs(event.units_delta)
    if event.event_type == EVENT_USE_UP:
        return -abs(event.units_delta)
    return 0


def on_hand(events: list) -> int:
    """Most recent checkpoint, plus deltas after it.

    MAY GO NEGATIVE, deliberately. Clamping here would destroy the evidence
    that the log and the shelf have diverged, which under consume-scanning is
    the first thing worth catching (#0314). The card clamps for display only.
    """
    total = 0
    for e in in_order(events):
        if e.event_type in CHECKPOINT_EVENTS:
            total = e.units_absolute          # an observed count
        else:
            total += signed(e)
    return total


def rate(events: list, product, now: datetime) -> dict:
    """Trailing-window consumption rate, falling back to the stored estimate.

    Requires a minimum count AND a minimum elapsed span: six scans in one
    afternoon is not a rate.

    The divisor is the days the log actually covers, capped at the window.
    Dividing by the full window before the log is that old spreads real
    consumption over days nobody was tracking - 11 daily scans over 11 days
    read as one every two days (2026-09-13, Premier caramel).
    """
    cutoff = now - timedelta(days=RATE_WINDOW_DAYS)
    used = [e for e in events if e.event_type == EVENT_USE_UP and _ts(e) >= cutoff]
    n = len(used)
    first = min((_ts(e) for e in events), default=None)
    span_days = (now - first).total_seconds() / 86400 if first else 0.0

    if n >= RATE_MIN_EVENTS and span_days >= RATE_MIN_DAYS:
        units = sum(abs(e.units_delta) for e in used)
        window_days = min(float(RATE_WINDOW_DAYS), span_days)
        return {"rate": units / window_days,
                "rate_source": RATE_SOURCE_MEASURED,
                "rate_sample_size": n, "rate_window_days": round(window_days, 1)}
    return {"rate": float(product.initial_rate_estimate or 0.0),
            "rate_source": RATE_SOURCE_ESTIMATED,
            "rate_sample_size": n, "rate_window_days": RATE_WINDOW_DAYS}


def days_of_supply(units: int, rate_value: float, rate_source: str,
                   has_events: bool = True) -> dict:
    """Days remaining, or None with a REASON.

    Never infinity. A zero rate means consumption STOPPED, not that stock is
    plentiful - and those want opposite responses (#0314).
    """
    if not has_events:
        # No record at all - absence of data, not a measurement of zero.
        return {"days_of_supply": None, "unknown_reason": REASON_NO_EVENTS}
    if rate_value and rate_value > 0:
        return {"days_of_supply": units / rate_value, "unknown_reason": None}
    reason = (REASON_AWAITING_FIRST if rate_source == RATE_SOURCE_ESTIMATED
              else REASON_NO_CONSUMPTION)
    return {"days_of_supply": None, "unknown_reason": reason}


def _segments(events: list) -> list[dict]:
    """Split the log at checkpoints.

    Comparing the observed count at a checkpoint against what the deltas
    predicted gives the drift - unscanned consumption, which is what compliance
    measures.
    """
    out: list[dict] = []
    start = None
    expected = scanned = stocked = 0
    for e in in_order(events):
        if e.event_type in CHECKPOINT_EVENTS:
            if start is not None:
                out.append({"start": start, "end": e,
                            "drift": e.units_absolute - expected,
                            "scanned": scanned, "stocked": stocked})
            start = e
            expected = e.units_absolute
            scanned = stocked = 0
        else:
            expected += signed(e)
            if e.event_type == EVENT_USE_UP:
                scanned += abs(e.units_delta)
            elif e.event_type == EVENT_STOCK_IN:
                stocked += abs(e.units_delta)
    return out


def compliance(events: list) -> dict:
    """Scanned consumption as a fraction of actual, for the last closed cycle.

    A cycle runs between `reconcile` events; `adjust` checkpoints inside are
    folded in rather than treated as boundaries - they are corrections, not
    cycle markers.
    """
    segs = _segments(events)
    if not segs:
        return {"compliance": None, "periods": 0}

    cycles: list[list[dict]] = []
    current: list[dict] = []
    for s in segs:
        current.append(s)
        if s["end"].event_type == EVENT_RECONCILE:
            cycles.append(current)
            current = []
    if not cycles:
        return {"compliance": None, "periods": 0}

    last = cycles[-1]
    scanned = sum(s["scanned"] for s in last)
    unscanned = sum(max(0, -s["drift"]) for s in last)   # left without a scan
    actual = scanned + unscanned
    return {"compliance": (scanned / actual) if actual > 0 else None,
            "periods": len(cycles),
            "scanned_units": scanned, "unscanned_units": unscanned}
