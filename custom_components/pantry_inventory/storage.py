"""Persistence: three collections in one Store."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import storage

from .const import STORAGE_KEY, STORAGE_VERSION_MAJOR, STORAGE_VERSION_MINOR
from .models import BarcodeRecord, ProductRecord, StockEventRecord


class PantryStore:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = storage.Store(
            hass, STORAGE_VERSION_MAJOR, STORAGE_KEY,
            minor_version=STORAGE_VERSION_MINOR,
        )
        self.products: dict[str, ProductRecord] = {}
        self.barcodes: dict[str, BarcodeRecord] = {}   # keyed by normalised code
        self.events: list[StockEventRecord] = []
        # product_id -> to-do item uid, for a to-do list backend (shopping_list.py).
        # quick_shopping_list carries the product_id on the item itself and needs none.
        self.list_links: dict[str, str] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        self.products = {d["product_id"]: ProductRecord.from_dict(d)
                         for d in data.get("products", [])}
        self.barcodes = {d["code"]: BarcodeRecord.from_dict(d)
                         for d in data.get("barcodes", [])}
        self.events = [StockEventRecord.from_dict(d) for d in data.get("events", [])]
        # In place: a to-do backend holds this dict, so it must not be replaced.
        self.list_links.clear()
        self.list_links.update(data.get("list_links") or {})

    async def async_save(self) -> None:
        # Events are never pruned: the log length IS its value - it is the only
        # thing that could answer "has our consumption actually changed?".
        await self._store.async_save({
            "products": [p.as_dict() for p in self.products.values()],
            "barcodes": [b.as_dict() for b in self.barcodes.values()],
            "events": [e.as_dict() for e in self.events],
            "list_links": self.list_links,
        })

    def events_for(self, product_id: str) -> list[StockEventRecord]:
        return [e for e in self.events if e.product_id == product_id]
