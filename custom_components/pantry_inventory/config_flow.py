"""Config and options flow for Pantry Inventory. Single instance.

Two settings (SW-82, 2026-11): which shopping list pushes go to, and the store names
a product can carry. Both live in the entry's options, so they can change later
under Configure. An entry with no options, which is every install made before this
flow asked anything, keeps quick_shopping_list and the original stores
(coordinator.PantryManager.configure).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (CONF_SHOPPING_LIST, CONF_STORES, DOMAIN, PANEL_TITLE,
                    SHOPPING_LIST_DOMAIN, STORE_OPTIONS)


def list_choices(hass: HomeAssistant) -> list[str]:
    """Every list a push could go to: quick_shopping_list where it's installed,
    then each to-do entity."""
    out = []
    if hass.services.has_service(SHOPPING_LIST_DOMAIN, "add_item"):
        out.append(SHOPPING_LIST_DOMAIN)
    out += sorted(hass.states.async_entity_ids("todo"))
    return out


def default_list(choices: list[str]) -> str | None:
    for preferred in (SHOPPING_LIST_DOMAIN, "todo.shopping_list"):
        if preferred in choices:
            return preferred
    return choices[0] if choices else None


def clean_stores(raw: Any) -> list[str]:
    """Store names as typed: trimmed, blanks dropped, duplicates removed, order kept."""
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    out: list[str] = []
    for s in (str(x).strip() for x in items):
        if s and s not in out:
            out.append(s)
    return out


def _schema(choices: list[str], current_list: str | None, current_stores: list[str]):
    return vol.Schema({
        vol.Required(CONF_SHOPPING_LIST, default=current_list): selector.SelectSelector(
            selector.SelectSelectorConfig(options=choices,
                                          mode=selector.SelectSelectorMode.DROPDOWN)),
        vol.Optional(CONF_STORES, default=current_stores): selector.TextSelector(
            selector.TextSelectorConfig(multiple=True)),
    })


class PantryInventoryConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        choices = list_choices(self.hass)
        if not choices:
            return self.async_abort(reason="no_lists")
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_SHOPPING_LIST) not in choices:
                errors[CONF_SHOPPING_LIST] = "unknown_list"
            else:
                return self.async_create_entry(title=PANEL_TITLE, data={}, options={
                    CONF_SHOPPING_LIST: user_input[CONF_SHOPPING_LIST],
                    CONF_STORES: clean_stores(user_input.get(CONF_STORES))})
        return self.async_show_form(step_id="user", errors=errors,
                                    data_schema=_schema(choices, default_list(choices), []))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PantryInventoryOptionsFlow()


class PantryInventoryOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        choices = list_choices(self.hass)
        opts = dict(self.config_entry.options or {})
        current_list = opts.get(CONF_SHOPPING_LIST, SHOPPING_LIST_DOMAIN)
        if current_list not in choices:
            # Keep showing a list that's gone missing rather than silently
            # swapping it: the pushes would move without anyone choosing that.
            choices = [current_list] + choices
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_SHOPPING_LIST) not in choices:
                errors[CONF_SHOPPING_LIST] = "unknown_list"
            else:
                return self.async_create_entry(data={
                    CONF_SHOPPING_LIST: user_input[CONF_SHOPPING_LIST],
                    CONF_STORES: clean_stores(user_input.get(CONF_STORES))})
        stores = opts.get(CONF_STORES, list(STORE_OPTIONS))
        return self.async_show_form(step_id="init", errors=errors,
                                    data_schema=_schema(choices, current_list, stores))
