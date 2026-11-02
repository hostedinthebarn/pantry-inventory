"""Where pushed items go: quick_shopping_list, or any Home Assistant to-do list.

The pantry needs four things from a shopping list: is this product already on it,
add it, tick it off when it's scanned back in, and re-stamp it when the product is
renamed. Each backend answers those four. The coordinator keeps the rules that
matter around them (never disarm a push on failure, never fail a save because the
list is down), so a backend only has to raise when something goes wrong.

- QuickShoppingListBackend: the original target, via quick_shopping_list's own
  services. Items carry a product_id, a store and a department natively.
- TodoListBackend: any `todo.*` entity (HA's Shopping List, Local To-do, Bring!,
  ...). A to-do item has no product field, so the pantry remembers which item it
  added for which product (`links`, kept in the pantry's own store) and also puts a
  `[pantry:<id>]` marker in the description where the list supports descriptions,
  so the link survives a lost store.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .const import SHOPPING_LIST_DOMAIN, SOURCE_TAG

TODO_DOMAIN = "todo"
# TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM. Sending a description to a list
# without it is refused, so it's only sent where the list says it can store one.
TODO_SET_DESCRIPTION = 64
TODO_ACTIVE = "needs_action"
TODO_DONE = "completed"


def marker(product_id: str) -> str:
    return f"[pantry:{product_id}]"


def todo_summary(name: str, quantity: int) -> str:
    """What the to-do item reads. A plain to-do list has no quantity field, so a
    product bought in pairs says so in its text."""
    return name if quantity <= 1 else f"{name} ×{quantity}"


class QuickShoppingListBackend:
    """quick_shopping_list, exactly as the pantry has always used it."""

    target = SHOPPING_LIST_DOMAIN

    def __init__(self, hass, store_options: tuple[str, ...]) -> None:
        self.hass = hass
        self.store_options = store_options

    async def _items(self) -> list[dict]:
        resp = await self.hass.services.async_call(
            SHOPPING_LIST_DOMAIN, "list_items", {}, blocking=True,
            return_response=True)
        return (resp or {}).get("items", [])

    async def has_active(self, product_id: str) -> bool:
        return any(it.get("product_id") == product_id and it.get("status") == "active"
                   for it in await self._items())

    async def add(self, p, unit_gtin: str) -> None:
        # The store IS tags[0] in quick_shopping_list, and choosing a store
        # replaces the whole tag list - so this is the ONLY tag we write.
        tags = ([p.default_store]
                if p.default_store in self.store_options and p.default_store != "All"
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
             "gtin": unit_gtin},
            blocking=True)

    async def mark_purchased(self, product_id: str) -> None:
        for it in await self._items():
            if it.get("product_id") == product_id and it.get("status") == "active":
                await self.hass.services.async_call(
                    SHOPPING_LIST_DOMAIN, "mark_purchased",
                    {"item_id": it["item_id"]}, blocking=True)

    async def restamp(self, p) -> list[tuple[str, list[str]]]:
        """Push a changed name, department or quantity onto ACTIVE items.
        Returns (item id, fields changed) for each item touched."""
        done = []
        for it in await self._items():
            if it.get("product_id") != p.product_id or it.get("status") != "active":
                continue
            updates: dict[str, Any] = {}
            if it.get("name") != p.name:
                updates["name"] = p.name
            if p.department and it.get("department") != p.department:
                updates["department"] = p.department
            if it.get("quantity") != str(p.purchase_quantity):
                updates["quantity"] = str(p.purchase_quantity)
            if not updates:
                continue
            await self.hass.services.async_call(
                SHOPPING_LIST_DOMAIN, "update_item",
                {"item_id": it["item_id"], **updates}, blocking=True)
            done.append((it["item_id"], sorted(updates)))
        return done


class TodoListBackend:
    """Any Home Assistant to-do list entity."""

    def __init__(self, hass, entity_id: str, links: dict[str, str],
                 save: Callable[[], Awaitable[None]]) -> None:
        self.hass = hass
        self.target = entity_id
        self.links = links          # product_id -> to-do item uid, persisted by `save`
        self._save = save

    def _supports_description(self) -> bool:
        state = self.hass.states.get(self.target)
        features = (state.attributes.get("supported_features", 0) if state else 0) or 0
        return bool(int(features) & TODO_SET_DESCRIPTION)

    async def _items(self) -> list[dict]:
        resp = await self.hass.services.async_call(
            TODO_DOMAIN, "get_items",
            {"entity_id": self.target, "status": [TODO_ACTIVE]},
            blocking=True, return_response=True)
        return ((resp or {}).get(self.target) or {}).get("items", [])

    def _find(self, product_id: str, items: list[dict]) -> dict | None:
        uid = self.links.get(product_id)
        for it in items:
            if uid and it.get("uid") == uid:
                return it
        tag = marker(product_id)
        for it in items:
            if tag in (it.get("description") or ""):
                return it
        return None

    async def has_active(self, product_id: str) -> bool:
        return self._find(product_id, await self._items()) is not None

    async def add(self, p, unit_gtin: str) -> None:
        summary = todo_summary(p.name, p.purchase_quantity)
        data: dict[str, Any] = {"entity_id": self.target, "item": summary}
        if self._supports_description():
            lines = [f"Store: {p.default_store}"] if p.default_store not in ("", "All") else []
            data["description"] = "\n".join(lines + [marker(p.product_id)])
        await self.hass.services.async_call(TODO_DOMAIN, "add_item", data, blocking=True)
        # todo.add_item returns nothing, so find the item it made: the newest
        # active one with this text that isn't already some other product's.
        taken = {u for pid, u in self.links.items() if pid != p.product_id}
        made = [it for it in await self._items()
                if it.get("summary") == summary and it.get("uid") not in taken]
        if made:
            self.links[p.product_id] = made[-1]["uid"]
            await self._save()

    async def mark_purchased(self, product_id: str) -> None:
        it = self._find(product_id, await self._items())
        if it is not None:
            await self.hass.services.async_call(
                TODO_DOMAIN, "update_item",
                {"entity_id": self.target, "item": it["uid"], "status": TODO_DONE},
                blocking=True)
        if self.links.pop(product_id, None) is not None:
            await self._save()

    async def restamp(self, p) -> list[tuple[str, list[str]]]:
        it = self._find(p.product_id, await self._items())
        summary = todo_summary(p.name, p.purchase_quantity)
        if it is None or it.get("summary") == summary:
            return []
        await self.hass.services.async_call(
            TODO_DOMAIN, "update_item",
            {"entity_id": self.target, "item": it["uid"], "rename": summary},
            blocking=True)
        return [(it["uid"], ["name"])]
