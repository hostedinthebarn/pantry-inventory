"""Pantry Inventory manager: scanning, derivation and the shopping-list push."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from .ulid import new_ulid

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import derive, gtin
from .const import (
    CHECKPOINT_EVENTS,
    DEPARTMENT_SLUGS,
    EVENT_ADJUST,
    EVENT_STOCK_IN,
    EVENT_TYPES,
    EVENT_USE_UP,
    POLICIES,
    POLICY_PAR,
    PRODUCT_ACTIVE,
    PRODUCT_ARCHIVED,
    PRODUCT_PROVISIONAL,
    SEED_UNITS,
    SHOPPING_LIST_DOMAIN,
    SOURCE_SEED,
    SOURCE_TAG,
    STORE_OPTIONS,
)
from .models import BarcodeRecord, ProductRecord, StockEventRecord
from .storage import PantryStore

_LOGGER = logging.getLogger(__name__)


class PantryError(RuntimeError):
    """A refusable failure: surfaced to the caller, not swallowed."""


class PantryManager:
    """Owns the Product catalogue and the Stock Event log."""

    def __init__(self, hass: HomeAssistant, store: PantryStore) -> None:
        self.hass = hass
        self.store = store
        self.product_entities: dict[str, Any] = {}
        self.summary_entities: list[Any] = []
        self.add_sensor_entities = None
        self.sensor_factory = None   # set by sensor.py; avoids a circular import

    # ---------- reads ----------

    def get_product(self, product_id: str) -> ProductRecord | None:
        return self.store.products.get(product_id)

    def get_products(self) -> list[ProductRecord]:
        return list(self.store.products.values())

    def resolve_barcode(self, code: str) -> BarcodeRecord | None:
        return self.store.barcodes.get(gtin.normalise(code))

    def state_for(self, product_id: str, now: datetime | None = None) -> dict[str, Any]:
        """Everything derived for one product. None of it is persisted."""
        p = self.get_product(product_id)
        if p is None:
            return {}
        now = now or dt_util.now()
        events = self.store.events_for(product_id)
        units = derive.on_hand(events)
        r = derive.rate(events, p, now)
        d = derive.days_of_supply(units, r["rate"], r["rate_source"], bool(events))
        c = derive.compliance(events)
        return {
            "product_id": p.product_id,
            "name": p.name,
            "unit_noun": p.unit_noun,
            "status": p.status,
            "on_hand": units,                      # TRUE value; may be negative
            "threshold_days": p.threshold_days,
            "policy": p.policy,
            "threshold_units": p.threshold_units,
            "purchase_quantity": p.purchase_quantity,
            "department": p.department,
            # The ONE definition of "needs reordering". async_evaluate, summary()
            # and the card all read this, so a policy can never mean one thing to
            # the pusher and another to the display.
            "below_threshold": self._below_threshold(
                p, units, d["days_of_supply"], bool(events)),
            "default_store": p.default_store,
            "push_armed": p.push_armed,
            "barcodes": {b.code: b.units for b in self.store.barcodes.values()
                         if b.product_id == product_id},
            "event_count": len(events),
            **r, **d,
            "compliance_last_cycle": c["compliance"],
            "compliance_periods": c["periods"],
        }

    @staticmethod
    def _below_threshold(p: ProductRecord, units: int, dos: float | None,
                         has_events: bool) -> bool:
        """Does this product need reordering?

        Under POLICY_PAR the question is answered in units and nothing else: a
        product with no rate worth measuring still has a shelf you can look at.
        Under the rate policy an unknown days-of-supply is NOT below threshold -
        absence of a measurement is not a measurement (#0314).

        `has_events` guards BOTH policies, and the par one needs it more. A
        product with no stock events derives on_hand 0, which under par is below
        every possible par - so without this, seeding the catalogue would push
        every product onto the shopping list before a single count was entered.
        That is the exact trap REASON_NO_EVENTS exists to document, and the par
        policy walks straight back into it. Caught by the verification suite.
        """
        if not has_events:
            return False
        if p.policy == POLICY_PAR:
            return units < p.threshold_units
        return dos is not None and dos < p.threshold_days

    def summary(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or dt_util.now()
        below = 0
        comps: list[float] = []
        for p in self.store.products.values():
            if p.status != PRODUCT_ACTIVE:
                continue
            s = self.state_for(p.product_id, now)
            if s.get("below_threshold"):
                below += 1
            if s.get("compliance_last_cycle") is not None:
                comps.append(s["compliance_last_cycle"])
        return {
            "products_below_threshold": below,
            "products_needing_naming": sum(
                1 for p in self.store.products.values()
                if p.status == PRODUCT_PROVISIONAL),
            "overall_compliance": (sum(comps) / len(comps)) if comps else None,
        }

    # ---------- writes ----------

    async def async_scan(self, code: str, direction: str,
                         source: str = "panel") -> dict[str, Any]:
        """Record a scan. NEVER loses one: an unknown code creates a provisional
        product rather than being refused, because a refusal mid-unload means the
        data is simply gone."""
        raw = (code or "").strip()
        if not gtin.is_valid_gtin(raw):
            raise PantryError(f"{raw!r} is not a valid barcode (check digit failed)")
        if direction not in (EVENT_STOCK_IN, EVENT_USE_UP):
            raise PantryError(f"direction must be {EVENT_STOCK_IN} or {EVENT_USE_UP}")

        norm = gtin.normalise(raw)
        bc = self.store.barcodes.get(norm)

        # A REMEMBERED code: the barcode survived its deleted product. Recreate
        # from what was kept, and re-link every sibling code at the same time -
        # otherwise the user rebuilds a mapping the system still holds (#0322).
        if bc is not None and self.get_product(bc.product_id) is None:
            stamp = dt_util.now().isoformat()
            self.store.products[bc.product_id] = ProductRecord(
                product_id=bc.product_id,
                name=bc.remembered_name or f"Recovered {norm[-6:]}",
                unit_noun=bc.remembered_unit_noun or "unit",
                status=PRODUCT_PROVISIONAL, created_at=stamp, updated_at=stamp)
            self.ensure_entity(bc.product_id)
            for sibling in self.store.barcodes.values():
                if sibling.product_id == bc.product_id:
                    sibling.remembered_name = ""
                    sibling.remembered_unit_noun = ""
            await self.store.async_save()

        if bc is None:
            pid = f"unknown_{norm[-6:]}"
            if pid not in self.store.products:
                stamp = dt_util.now().isoformat()
                self.store.products[pid] = ProductRecord(
                    product_id=pid, name=f"Unknown item {norm[-6:]}",
                    status=PRODUCT_PROVISIONAL, created_at=stamp, updated_at=stamp)
            self.ensure_entity(pid)
            bc = BarcodeRecord(code=norm, product_id=pid, units=1)
            self.store.barcodes[norm] = bc

        # SEED. A use_up scan against a product with no stock events at all
        # means the very first thing that ever happened to it was someone taking
        # one off the shelf - so there was at least one there (Gary, 2026-09-04).
        # Recording that floor as an observed checkpoint is what stops the first
        # scan of a new product landing at -1 and reading "needs a count" on day
        # one, and it is what lets a par product push on its first use.
        #
        # Deliberately NOT applied to stock_in: the scan itself establishes the
        # stock there, and a seed would double it. Deliberately keyed on "no
        # events" rather than "new barcode": a second barcode attached to a
        # product that already has history must not re-seed it.
        #
        # The seed is `bc.units`, not a flat 1: at least one of whatever THIS
        # code counts was on the shelf. That gives one invariant worth holding -
        # a first use_up always lands on-hand at exactly 0, never negative,
        # whether the code is a bottle or a case.
        if direction == EVENT_USE_UP and not self.store.events_for(bc.product_id):
            await self._append_event(
                bc.product_id, EVENT_ADJUST,
                absolute=max(SEED_UNITS, bc.units), source=SOURCE_SEED,
                raw_code=raw)

        await self._append_event(bc.product_id, direction, delta=bc.units,
                                 source=source, raw_code=raw)
        return {
            "product_id": bc.product_id,
            "units": bc.units,
            "provisional":
                self.store.products[bc.product_id].status == PRODUCT_PROVISIONAL,
            "state": self.state_for(bc.product_id),
        }

    async def async_set_count(self, product_id: str, units: int,
                              event_type: str = EVENT_ADJUST,
                              source: str = "panel") -> dict[str, Any]:
        """Record an OBSERVED count - a checkpoint.

        Stored absolute, never converted to a delta: turning "there are 7 here"
        into "+3" at write time bakes in whatever the system believed then, and
        launders any error beyond recovery.
        """
        if event_type not in CHECKPOINT_EVENTS:
            raise PantryError(f"{event_type} is not a checkpoint event")
        if self.get_product(product_id) is None:
            raise PantryError(f"unknown product {product_id!r}")
        await self._append_event(product_id, event_type,
                                 absolute=int(units), source=source)
        return self.state_for(product_id)

    async def _append_event(self, product_id: str, event_type: str, delta: int = 0,
                            absolute: int = 0, source: str = "panel",
                            raw_code: str = "") -> None:
        if event_type not in EVENT_TYPES:
            raise PantryError(f"unknown event type {event_type!r}")
        before = derive.on_hand(self.store.events_for(product_id))
        self.store.events.append(StockEventRecord(
            event_id=new_ulid(), product_id=product_id, event_type=event_type,
            timestamp=dt_util.now().isoformat(),
            units_delta=int(delta), units_absolute=int(absolute),
            source=source, raw_code=raw_code))
        after = derive.on_hand(self.store.events_for(product_id))
        await self.store.async_save()

        # Re-arm on ANY on-hand increase, not on stock_in alone: a restock
        # recorded as an `adjust` would otherwise leave the push disarmed
        # forever and the next depletion would never be flagged (#0314).
        if after > before:
            p = self.store.products[product_id]
            if not p.push_armed:
                p.push_armed = True
                await self.store.async_save()
            # ...but marking the shopping list PURCHASED follows a narrower
            # rule: only a `stock_in`, because only a stock_in means stock
            # ARRIVED. #0315 originally gave both side-effects the same
            # condition so they could not drift apart, which was reasonable
            # until it produced a real fault: correcting a count upward
            # ("there are actually 4 here") silently marked an active list
            # item purchased, even though nothing had been bought. Hit while
            # setting up the Michelob product, 2026-09-04.
            #
            # The two harms are not symmetric, which is what settles it:
            #   - too broad: something you still need vanishes off the list,
            #     invisibly, and you find out in the shop.
            #   - too narrow: a restock recorded as an adjust leaves the item
            #     on the list and you tick it off by hand. Visible, and
            #     self-correcting.
            # Set-absolute events (`adjust`, `reconcile`) are OBSERVATIONS of
            # what is on the shelf, not arrivals - a reconcile is step one of a
            # restock, and the stock_in that follows is the part that means a
            # purchase happened.
            if event_type == EVENT_STOCK_IN:
                await self._mark_purchased(product_id)

        self._write_state(product_id)

        # Do NOT push while stock is arriving. An increase means a restock is in
        # progress, and evaluating here would mark the list item purchased and then
        # immediately re-add it on the next pack scanned - churning the list. The
        # daily tick still catches anything genuinely below threshold afterwards.
        if after <= before:
            await self.async_evaluate(product_id)

    def _write_state(self, product_id: str) -> None:
        """Write ONLY the affected product entity, never a global refresh."""
        ent = self.product_entities.get(product_id)
        if ent is not None:
            ent.async_write_ha_state()
        for ent in self.summary_entities:
            ent.async_write_ha_state()

    # ---------- shopping list ----------

    async def async_evaluate(self, product_id: str | None = None) -> None:
        ids = [product_id] if product_id else list(self.store.products)
        for pid in ids:
            p = self.get_product(pid)
            if p is None or p.status != PRODUCT_ACTIVE or not p.push_armed:
                continue
            if not self.state_for(pid).get("below_threshold"):
                continue
            if await self._push(p):
                p.push_armed = False          # ONLY on a confirmed success
                await self.store.async_save()
                # The record is not the entity: without this write the card keeps
                # serving the pre-push attributes and reads push_armed true for
                # something already sitting on the shopping list. Same one-entity
                # write _append_event uses - never a global refresh (#0344).
                self._write_state(p.product_id)

    async def _push(self, p: ProductRecord) -> bool:
        """Add to quick_shopping_list. True only on a confirmed add.

        A failed call must leave push_armed set: disarming on failure loses the
        push permanently, since re-arming needs on-hand to increase - which will
        not happen while nobody knows they are out (#0315).
        """
        try:
            for it in await self._list_items():
                if it.get("product_id") == p.product_id and it.get("status") == "active":
                    return True                # already there; treat as done
            # The store IS tags[0] in quick_shopping_list, and choosing a store
            # replaces the whole tag list - so this is the ONLY tag we write.
            tags = ([p.default_store]
                    if p.default_store in STORE_OPTIONS and p.default_store != "All"
                    else [])
            await self.hass.services.async_call(
                SHOPPING_LIST_DOMAIN, "add_item",
                # `store` is the field the list moved to in its storage minor 2;
                # `tags` is sent alongside it for the dual-write window, so this
                # call is correct against a list build from either side of that
                # change and the two components need not be deployed together.
                # `gtin` lets the list fetch an exact product picture instead
                # of guessing one from the name. It is additive: a list build
                # that predates it rejects unknown keys, so the two components
                # still deploy independently in that direction only.
                # Quantity is the product's, not a constant. It is only ever
                # a hint for the trolley: nothing reads it back, and stock is
                # scanned in per unit, so an item bought as a pair still lands
                # in inventory as two separate stock_in scans.
                {"name": p.name, "quantity": str(p.purchase_quantity),
                 "source": SOURCE_TAG,
                 "store": p.default_store, "tags": tags,
                 "department": p.department, "product_id": p.product_id,
                 "gtin": self._unit_barcode(p.product_id)},
                blocking=True)
            return True
        except Exception as err:  # noqa: BLE001 - must not disarm on any failure
            _LOGGER.warning("pantry: shopping list push failed for %s: %s",
                            p.product_id, err)
            return False

    def _unit_barcode(self, product_id: str) -> str:
        """The code on ONE of these, not on the case.

        A pack code (units 18) is a distribution barcode that no consumer
        database carries, so it would return nothing. The unit code is the one
        printed on the bottle and the one Open Food Facts knows.
        """
        codes = [b.code for b in self.store.barcodes.values()
                 if b.product_id == product_id and b.units == 1]
        return codes[0] if codes else ""

    async def _mark_purchased(self, product_id: str) -> None:
        try:
            for it in await self._list_items():
                if it.get("product_id") == product_id and it.get("status") == "active":
                    await self.hass.services.async_call(
                        SHOPPING_LIST_DOMAIN, "mark_purchased",
                        {"item_id": it["item_id"]}, blocking=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("pantry: mark_purchased failed for %s: %s", product_id, err)

    async def _list_items(self) -> list[dict]:
        resp = await self.hass.services.async_call(
            SHOPPING_LIST_DOMAIN, "list_items", {}, blocking=True,
            return_response=True)
        return (resp or {}).get("items", [])

    # ---------- catalogue ----------

    async def async_save_product(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a Product. Naming a provisional one activates it."""
        pid = (data.get("product_id") or "").strip()
        if not pid:
            raise PantryError("product_id is required")

        # Validate BEFORE mutating anything. Checking afterwards left a refused
        # value stuck on the in-memory record, so every subsequent save of that
        # product failed too - a refusal must leave state exactly as it was.
        incoming_store = data.get("default_store")
        if incoming_store is not None and incoming_store not in STORE_OPTIONS \
                and incoming_store != "":
            raise PantryError(
                f"default_store {incoming_store!r} is not one of {STORE_OPTIONS}. "
                "An unrecognised tag lands the item on no list at all.")
        incoming_policy = data.get("policy")
        if incoming_policy is not None and incoming_policy not in POLICIES:
            raise PantryError(
                f"policy {incoming_policy!r} is not one of {POLICIES}.")
        # A par of zero pushes forever: on_hand < 0 is false only while stock is
        # negative, so the product would sit permanently below threshold and the
        # alert would stop meaning anything - the same trap DEFAULT_THRESHOLD_DAYS
        # documents for the rate policy.
        incoming_units = data.get("threshold_units")
        if incoming_units is not None and int(incoming_units) < 1:
            raise PantryError("threshold_units must be at least 1.")
        # Zero or fewer would push an item nobody can act on - "buy 0 boxes" -
        # and the field's whole job is to say how many to put in the trolley.
        incoming_qty = data.get("purchase_quantity")
        if incoming_qty is not None and int(incoming_qty) < 1:
            raise PantryError("purchase_quantity must be at least 1.")
        incoming_dept = data.get("department")
        if incoming_dept:
            incoming_dept = str(incoming_dept).strip()
            if incoming_dept not in DEPARTMENT_SLUGS:
                raise PantryError(
                    f"department {incoming_dept!r} is not a known slug. "
                    "An unrecognised department groups the item under a heading "
                    "no walk order knows, so it renders where nothing sorts.")
        stamp = dt_util.now().isoformat()
        p = self.store.products.get(pid)
        # Captured BEFORE the mutation: the re-stamp fires only on an actual
        # change, so an unrelated save does not touch the shopping list.
        was_name = p.name if p is not None else ""
        was_department = p.department if p is not None else ""
        was_quantity = p.purchase_quantity if p is not None else 0
        if p is None:
            p = ProductRecord(product_id=pid, name=data.get("name") or pid,
                              created_at=stamp, updated_at=stamp)
            self.store.products[pid] = p
            self.ensure_entity(pid)

        for field in ("name", "unit_noun", "default_store"):
            if field in data and data[field] is not None:
                setattr(p, field, data[field])
        if "initial_rate_estimate" in data and data["initial_rate_estimate"] is not None:
            p.initial_rate_estimate = float(data["initial_rate_estimate"])
        if "threshold_days" in data and data["threshold_days"] is not None:
            p.threshold_days = int(data["threshold_days"])
        if incoming_policy is not None:
            p.policy = incoming_policy
        if incoming_units is not None:
            p.threshold_units = int(incoming_units)
        if incoming_qty is not None:
            p.purchase_quantity = int(incoming_qty)
        if incoming_dept is not None:
            p.department = incoming_dept
        if "status" in data and data["status"]:
            p.status = data["status"]
        elif p.status == PRODUCT_PROVISIONAL and data.get("name"):
            # Naming it is what makes it real - no separate "activate" step.
            p.status = PRODUCT_ACTIVE

        p.updated_at = stamp
        await self.store.async_save()
        self._write_state(pid)
        if (p.name != was_name or p.department != was_department
                or p.purchase_quantity != was_quantity):
            await self._restamp_list_items(p)
        await self.async_evaluate(pid)
        return self.state_for(pid)

    async def _restamp_list_items(self, p: ProductRecord) -> None:
        """Push a changed name, department or quantity onto ACTIVE items.

        Product and list item are separate records joined by product_id (ADR
        0018), so renaming a Product used to leave the list showing the old
        name until the item was bought and re-pushed. That is not cosmetic: the
        moment you look a product up is usually the moment it is on the list,
        because naming a freshly scanned provisional is what pushes it.

        Three deliberate limits:


        - Only on an ACTUAL change, never on every save. The pantry does not
          own the name on the list continuously - it propagates a change at the
          moment you make one. A name you edited by hand on the list therefore
          survives until the next explicit rename of the Product, which is a
          deliberate act and reasonably means "call it this everywhere".

        - PURCHASED items are left alone. Rewriting the name on a completed
          purchase edits history for no benefit.

        - Failure is logged, never raised. A shopping list that is down must not
          make saving a Product fail - the same reasoning that stops _push
          disarming on failure.
        """
        try:
            for it in await self._list_items():
                if it.get("product_id") != p.product_id:
                    continue
                if it.get("status") != "active":
                    continue
                updates: dict[str, Any] = {}
                if it.get("name") != p.name:
                    updates["name"] = p.name
                if p.department and it.get("department") != p.department:
                    updates["department"] = p.department
                # Same rule as the name: propagated at the moment you change
                # it, not owned continuously. Deciding a product is bought in
                # pairs is a deliberate act that reasonably means "including
                # the one already on the list" - otherwise the setting does
                # nothing until the current item is bought and re-pushed,
                # which is exactly the cycle it exists to fix.
                if it.get("quantity") != str(p.purchase_quantity):
                    updates["quantity"] = str(p.purchase_quantity)
                if not updates:
                    continue
                await self.hass.services.async_call(
                    SHOPPING_LIST_DOMAIN, "update_item",
                    {"item_id": it["item_id"], **updates}, blocking=True)
                _LOGGER.info("pantry: re-stamped list item %s for %s (%s)",
                             it["item_id"], p.product_id,
                             ", ".join(sorted(updates)))
        except Exception as err:  # noqa: BLE001 - must not fail the save
            _LOGGER.warning("pantry: could not re-stamp list items for %s: %s",
                            p.product_id, err)

    async def async_attach_barcode(self, code: str, product_id: str,
                                   units: int = 1) -> dict[str, Any]:
        """Point a barcode at a product, with the units THAT code represents.

        A code maps to exactly one product, so reassigning is refused rather
        than done silently - two products sharing a code would make on_hand
        meaningless for both.
        """
        raw = (code or "").strip()
        if not gtin.is_valid_gtin(raw):
            raise PantryError(f"{raw!r} is not a valid barcode (check digit failed)")
        if self.get_product(product_id) is None:
            raise PantryError(f"unknown product {product_id!r}")
        if int(units) < 1:
            raise PantryError("units must be at least 1")

        norm = gtin.normalise(raw)
        existing = self.store.barcodes.get(norm)
        if existing is not None and existing.product_id != product_id:
            raise PantryError(
                f"barcode {norm} is already attached to {existing.product_id!r}. "
                "Detach it there first rather than reassigning silently.")

        self.store.barcodes[norm] = BarcodeRecord(
            code=norm, product_id=product_id, units=int(units))
        await self.store.async_save()
        self._write_state(product_id)
        return self.state_for(product_id)

    def write_all_states(self) -> None:
        """Used by the daily tick only - days_of_supply moves for every product
        as the rate window slides, so this is the one time a full write is right."""
        for ent in self.product_entities.values():
            ent.async_write_ha_state()
        for ent in self.summary_entities:
            ent.async_write_ha_state()

    def ensure_entity(self, product_id: str) -> None:
        """Give a newly-created product a sensor straight away.

        Without this, a product created by scanning an unknown code has no
        entity until the next restart - so the naming queue would show it while
        nothing in HA could see it.
        """
        if product_id in self.product_entities:
            return
        if self.sensor_factory is None or self.add_sensor_entities is None:
            return
        entity = self.sensor_factory(product_id)
        self.product_entities[product_id] = entity
        self.add_sensor_entities([entity])

    async def async_remove_product_entity(self, product_id: str) -> None:
        """Delete a product's entity from the state machine AND the registry.

        async_remove() alone is not enough: for an entity with a unique_id the
        entity-registry entry survives, HA restores it on the next start, and it
        sits there unavailable forever. The registry removal is the part that
        actually deletes it (#0304).
        """
        entity = self.product_entities.pop(product_id, None)
        if entity is None:
            return
        entity_id = getattr(entity, "entity_id", None)
        if entity_id:
            await entity.async_remove()
            registry = er.async_get(self.hass)
            if registry.async_get(entity_id) is not None:
                registry.async_remove(entity_id)

    # ---------- removal ----------

    async def async_discard_provisional(self, product_id: str) -> dict[str, Any]:
        """Throw away a never-named product. Deliberately easy.

        A mis-scan has no name, threshold or history worth guarding, and junk
        accumulating in the naming queue is how that flow dies (#0322). Its
        barcodes go too: an auto-created code with no name behind it holds
        nothing worth remembering.
        """
        p = self.get_product(product_id)
        if p is None:
            raise PantryError(f"unknown product {product_id!r}")
        if p.status != PRODUCT_PROVISIONAL:
            raise PantryError(
                f"{product_id!r} is {p.status}, not provisional. "
                "Archive it and use delete_product instead.")
        codes = [c for c, b in self.store.barcodes.items() if b.product_id == product_id]
        for c in codes:
            del self.store.barcodes[c]
        self.store.events = [e for e in self.store.events if e.product_id != product_id]
        del self.store.products[product_id]
        await self.store.async_save()
        await self.async_remove_product_entity(product_id)
        _LOGGER.info("pantry: discarded provisional %s (%d barcode(s))",
                     product_id, len(codes))
        return {"discarded": product_id, "barcodes_removed": len(codes)}

    async def async_delete_product(self, product_id: str,
                                   confirm_name: str) -> dict[str, Any]:
        """Delete an ARCHIVED product. Deliberately hard.

        Requires the exact name retyped: a confirm dialog becomes muscle memory
        inside a week, whereas retyping forces you to look at what you are
        deleting. There is no panel button for this on purpose (#0322).
        """
        p = self.get_product(product_id)
        if p is None:
            raise PantryError(f"unknown product {product_id!r}")
        if p.status != PRODUCT_ARCHIVED:
            raise PantryError(
                f"{product_id!r} is {p.status}. Archive it first - deletion is "
                "deliberately a two-step operation.")
        if (confirm_name or "").strip() != p.name:
            raise PantryError(
                f"confirm_name does not match. To delete this product, pass its "
                f"exact name: {p.name!r}")

        events = self.store.events_for(product_id)
        stamps = sorted(e.timestamp for e in events)
        codes = [b for b in self.store.barcodes.values() if b.product_id == product_id]

        # Barcodes SURVIVE, carrying what it costs a scan and a decision to
        # rebuild. Events do NOT: orphaned events sit in a log whose sum defines
        # on_hand, belonging to nothing.
        for b in codes:
            b.remembered_name = p.name
            b.remembered_unit_noun = p.unit_noun
        self.store.events = [e for e in self.store.events if e.product_id != product_id]
        del self.store.products[product_id]
        await self.store.async_save()

        await self.async_remove_product_entity(product_id)

        # The trace, so a later "where did that go?" has an answer.
        _LOGGER.info(
            "pantry: deleted product %s (%r): %d event(s) removed, range %s..%s; "
            "%d barcode(s) kept as remembered codes: %s",
            product_id, p.name, len(events),
            stamps[0] if stamps else "-", stamps[-1] if stamps else "-",
            len(codes), ", ".join(b.code for b in codes) or "none")
        return {"deleted": product_id, "events_removed": len(events),
                "barcodes_remembered": [b.code for b in codes]}

    async def async_attach_to_existing(self, provisional_id: str, target_id: str,
                                       units: int) -> dict[str, Any]:
        """Fold a provisional product into an existing one.

        The case a store's pack size creates: Costco sells the 18, Walmart the
        12, and the bottle carries a third code - all one Product. Scanning the
        unfamiliar code makes a provisional, and without this there is no way to
        say "this is the same thing" (#0316 gap, found in use).

        Its scans are REPLAYED onto the target at the corrected unit count,
        because they were recorded before anything knew a case meant twelve.
        Discarding them would violate the never-lose-a-scan rule the whole
        unknown-code flow exists to honour.
        """
        prov = self.get_product(provisional_id)
        target = self.get_product(target_id)
        if prov is None:
            raise PantryError(f"unknown product {provisional_id!r}")
        if target is None:
            raise PantryError(f"unknown target product {target_id!r}")
        if provisional_id == target_id:
            raise PantryError("cannot attach a product to itself")
        if prov.status != PRODUCT_PROVISIONAL:
            raise PantryError(
                f"{provisional_id!r} is {prov.status}, not provisional. Only a "
                "never-named product can be folded into another.")
        if int(units) < 1:
            raise PantryError("units must be at least 1")

        moved = []
        for b in self.store.barcodes.values():
            if b.product_id == provisional_id:
                b.product_id = target_id
                b.units = int(units)
                b.remembered_name = ""
                b.remembered_unit_noun = ""
                moved.append(b.code)

        # Replay at the CORRECTED unit count, keeping the original timestamps so
        # the rate window still sees when they actually happened. Checkpoints are
        # not replayed: an absolute count of the provisional says nothing about
        # the target's shelf.
        before = derive.on_hand(self.store.events_for(target_id))
        replayed = 0
        replayed_stock_in = False
        for e in self.store.events_for(provisional_id):
            if e.event_type in (EVENT_STOCK_IN, EVENT_USE_UP):
                self.store.events.append(StockEventRecord(
                    event_id=new_ulid(), product_id=target_id,
                    event_type=e.event_type, timestamp=e.timestamp,
                    units_delta=int(units), units_absolute=0,
                    source=e.source, raw_code=e.raw_code))
                replayed += 1
                replayed_stock_in |= e.event_type == EVENT_STOCK_IN

        self.store.events = [e for e in self.store.events
                             if e.product_id != provisional_id]
        del self.store.products[provisional_id]
        after = derive.on_hand(self.store.events_for(target_id))

        # The same two side-effects `_append_event` applies, which this path
        # bypassed by appending directly. Without them a restock scanned under an
        # unfamiliar pack code left the target disarmed forever and its list
        # item active (Premier caramel, attached 2026-09-06, found 2026-09-13).
        if after > before:
            target.push_armed = True
            if replayed_stock_in:
                await self._mark_purchased(target_id)
        await self.store.async_save()

        entity = self.product_entities.pop(provisional_id, None)
        if entity is not None and getattr(entity, "entity_id", None):
            await entity.async_remove()

        _LOGGER.info("pantry: folded %s into %s - %d barcode(s) %s at %d units, "
                     "%d scan(s) replayed", provisional_id, target_id,
                     len(moved), ",".join(moved), int(units), replayed)
        self._write_state(target_id)
        # As in `_append_event`: no push while stock is arriving, or the item
        # just marked purchased is re-added straight away. The daily tick
        # catches anything still genuinely below threshold.
        if after <= before:
            await self.async_evaluate(target_id)
        return {"attached_to": target_id, "barcodes_moved": moved,
                "scans_replayed": replayed, "units": int(units),
                "state": self.state_for(target_id)}
