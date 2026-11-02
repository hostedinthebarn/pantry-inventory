"""Persisted shapes. Three collections.

on_hand, rate and compliance are NOT here: they are pure functions of the event
log, derived on demand (ADR 0017). The single exception is `push_armed` - an
outward side-effect is not reconstructible from the log, so it is stored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from .const import (
    DEFAULT_POLICY,
    DEFAULT_PURCHASE_QUANTITY,
    DEFAULT_THRESHOLD_DAYS,
    DEFAULT_THRESHOLD_UNITS,
    PRODUCT_ACTIVE,
)


def _prune(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Drop keys the dataclass does not know about, so a downgrade survives.

    Without this, a newer field written to storage makes an older build raise
    TypeError on load - the same trap found in quick_shopping_list (#0315).
    """
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in known}


@dataclass(slots=True)
class ProductRecord:
    """A durable, barcoded identity. Permanent; contrast a shopping list item."""

    product_id: str
    name: str
    unit_noun: str = "unit"
    initial_rate_estimate: float = 0.0   # the ONLY rate ever persisted
    threshold_days: int = DEFAULT_THRESHOLD_DAYS
    # How this product decides it needs reordering. Both thresholds are kept on
    # the record whichever is in force, so switching policy and switching back
    # does not lose the other one's setting.
    policy: str = DEFAULT_POLICY
    threshold_units: int = DEFAULT_THRESHOLD_UNITS
    # How many to buy when it does need reordering - stamped on the shopping
    # list item and read by nothing else. Separate from threshold_units on
    # purpose; see the note in const.py.
    purchase_quantity: int = DEFAULT_PURCHASE_QUANTITY
    # Where this sits in the shop, as a quick_shopping_list department slug.
    # Held HERE rather than derived from the name each time it is listed: the
    # Product is the durable identity, so classifying it is a decision made once
    # (usually at barcode lookup) rather than a guess repeated on every push.
    department: str = ""
    status: str = PRODUCT_ACTIVE
    default_store: str = ""              # "" / "All" -> push with no tag
    push_armed: bool = True
    created_at: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProductRecord":
        p = _prune(cls, dict(data))
        p.setdefault("unit_noun", "unit")
        p.setdefault("initial_rate_estimate", 0.0)
        p.setdefault("threshold_days", DEFAULT_THRESHOLD_DAYS)
        p.setdefault("policy", DEFAULT_POLICY)
        p.setdefault("threshold_units", DEFAULT_THRESHOLD_UNITS)
        p.setdefault("purchase_quantity", DEFAULT_PURCHASE_QUANTITY)
        p.setdefault("department", "")
        p.setdefault("status", PRODUCT_ACTIVE)
        p.setdefault("default_store", "")
        p.setdefault("push_armed", True)
        p.setdefault("created_at", "")
        p.setdefault("updated_at", "")
        return cls(**p)


@dataclass(slots=True)
class BarcodeRecord:
    """The normalised code IS the id - a code maps to exactly one product by
    definition, so a synthetic key would only invite duplicates."""

    code: str          # normalised GTIN-14
    product_id: str
    units: int = 1     # case code -> 18, bottle code -> 1
    # Set when the product is deleted. The code->units mapping costs a physical
    # scan and a naming decision, and is identical every time the product is
    # bought again - so it OUTLIVES the product (ADR 0017, amended by #0322).
    remembered_name: str = ""
    remembered_unit_noun: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BarcodeRecord":
        p = _prune(cls, dict(data))
        p.setdefault("units", 1)
        p.setdefault("remembered_name", "")
        p.setdefault("remembered_unit_noun", "")
        return cls(**p)


@dataclass(slots=True)
class StockEventRecord:
    """The source of truth. Append-only; never pruned."""

    event_id: str
    product_id: str
    event_type: str
    timestamp: str
    units_delta: int = 0        # stock_in / use_up
    units_absolute: int = 0     # adjust / reconcile - the OBSERVED count
    source: str = "panel"       # panel | service | assist
    raw_code: str = ""          # exactly what the decoder returned; forensic

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StockEventRecord":
        p = _prune(cls, dict(data))
        p.setdefault("units_delta", 0)
        p.setdefault("units_absolute", 0)
        p.setdefault("source", "panel")
        p.setdefault("raw_code", "")
        return cls(**p)
