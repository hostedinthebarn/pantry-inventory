"""Pantry Inventory integration."""

from __future__ import annotations

import logging
from functools import wraps

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change

from . import websocket
from .const import (
    DEPARTMENT_SLUGS,
    DOMAIN,
    EVENT_ADJUST,
    EVENT_RECONCILE,
    EVENT_STOCK_IN,
    EVENT_USE_UP,
    POLICIES,
    PRODUCT_STATUSES,
    RECOMPUTE_HOUR,
    RECOMPUTE_MINUTE,
)
from .coordinator import PantryError, PantryManager
from .panel import async_register_panel, async_remove_panel
from .storage import PantryStore

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


def _as_service_error(func):
    """Convert a refusal into ServiceValidationError.

    NOTE: HA's REST service endpoint flattens ANY handler exception to an
    opaque 500 regardless of class, so the message only reaches the log and the
    websocket. Refusable writes therefore have websocket twins - that is the
    path a caller should use when it needs to know WHY (#0312 adapter note).
    """

    @wraps(func)
    async def wrapper(call: ServiceCall):
        try:
            return await func(call)
        except PantryError as err:
            raise ServiceValidationError(str(err)) from err
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    return wrapper


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = PantryStore(hass)
    await store.async_load()
    manager = PantryManager(hass, store)
    manager.configure(dict(getattr(entry, "options", None) or {}))
    entry.runtime_data = manager
    # Changing the shopping list or the stores in the options flow reloads the entry.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    hass.data.setdefault(DOMAIN, {})["manager"] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_panel(hass, entry)
    websocket.async_register(hass)

    @_as_service_error
    async def handle_scan(call: ServiceCall):
        return await manager.async_scan(
            call.data["code"], call.data["direction"],
            call.data.get("source", "service"))

    @_as_service_error
    async def handle_set_count(call: ServiceCall):
        return await manager.async_set_count(
            call.data["product_id"], call.data["units"],
            call.data.get("event_type", EVENT_ADJUST),
            call.data.get("source", "service"))

    @_as_service_error
    async def handle_save_product(call: ServiceCall):
        return await manager.async_save_product(dict(call.data))

    @_as_service_error
    async def handle_attach_barcode(call: ServiceCall):
        return await manager.async_attach_barcode(
            call.data["code"], call.data["product_id"], call.data.get("units", 1))

    async def handle_list_products(call: ServiceCall):
        return {"products": [manager.state_for(p.product_id)
                             for p in manager.get_products()],
                "summary": manager.summary()}

    @_as_service_error
    async def handle_discard_provisional(call: ServiceCall):
        return await manager.async_discard_provisional(call.data["product_id"])

    @_as_service_error
    async def handle_delete_product(call: ServiceCall):
        return await manager.async_delete_product(
            call.data["product_id"], call.data["confirm_name"])

    @_as_service_error
    async def handle_attach_to_existing(call: ServiceCall):
        return await manager.async_attach_to_existing(
            call.data["provisional_id"], call.data["target_id"], call.data["units"])

    @_as_service_error
    async def handle_evaluate(call: ServiceCall):
        await manager.async_evaluate()

    hass.services.async_register(
        DOMAIN, "scan", handle_scan,
        schema=vol.Schema({
            vol.Required("code"): cv.string,
            vol.Required("direction"): vol.In([EVENT_STOCK_IN, EVENT_USE_UP]),
            vol.Optional("source"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL)

    hass.services.async_register(
        DOMAIN, "set_count", handle_set_count,
        schema=vol.Schema({
            vol.Required("product_id"): cv.string,
            vol.Required("units"): vol.Coerce(int),
            vol.Optional("event_type"): vol.In([EVENT_ADJUST, EVENT_RECONCILE]),
            vol.Optional("source"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL)

    hass.services.async_register(
        DOMAIN, "save_product", handle_save_product,
        schema=vol.Schema({
            vol.Required("product_id"): cv.string,
            vol.Optional("name"): cv.string,
            vol.Optional("unit_noun"): cv.string,
            vol.Optional("initial_rate_estimate"): vol.Coerce(float),
            vol.Optional("threshold_days"): vol.Coerce(int),
            vol.Optional("policy"): vol.In(POLICIES),
            vol.Optional("threshold_units"): vol.Coerce(int),
            vol.Optional("purchase_quantity"): vol.Coerce(int),
            vol.Optional("department"): vol.In(list(DEPARTMENT_SLUGS) + [""]),
            vol.Optional("default_store"): cv.string,  # checked against the configured stores by the coordinator
            vol.Optional("status"): vol.In(PRODUCT_STATUSES),
        }),
        supports_response=SupportsResponse.OPTIONAL)

    hass.services.async_register(
        DOMAIN, "attach_barcode", handle_attach_barcode,
        schema=vol.Schema({
            vol.Required("code"): cv.string,
            vol.Required("product_id"): cv.string,
            vol.Optional("units"): vol.Coerce(int),
        }),
        supports_response=SupportsResponse.OPTIONAL)

    hass.services.async_register(
        DOMAIN, "list_products", handle_list_products,
        schema=vol.Schema({}), supports_response=SupportsResponse.ONLY)

    hass.services.async_register(
        DOMAIN, "discard_provisional", handle_discard_provisional,
        schema=vol.Schema({vol.Required("product_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL)

    # confirm_name is REQUIRED and must match exactly. Deliberately no panel
    # button - deletion is a trip to Developer Tools, not something fat-fingered
    # one-handed at the fridge (#0322).
    hass.services.async_register(
        DOMAIN, "delete_product", handle_delete_product,
        schema=vol.Schema({vol.Required("product_id"): cv.string,
                           vol.Required("confirm_name"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL)

    hass.services.async_register(
        DOMAIN, "attach_to_existing", handle_attach_to_existing,
        schema=vol.Schema({vol.Required("provisional_id"): cv.string,
                           vol.Required("target_id"): cv.string,
                           vol.Required("units"): vol.Coerce(int)}),
        supports_response=SupportsResponse.OPTIONAL)

    hass.services.async_register(
        DOMAIN, "evaluate", handle_evaluate, schema=vol.Schema({}))

    # Days of supply decays with wall-clock time even when on_hand does not,
    # because the rate window slides underneath it. Daily is the right cadence:
    # the figure is measured in days, so sub-day precision is noise (#0314).
    async def _daily(now):
        await manager.async_evaluate()
        manager.write_all_states()

    entry.async_on_unload(
        async_track_time_change(hass, _daily, hour=RECOMPUTE_HOUR,
                               minute=RECOMPUTE_MINUTE, second=0))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_remove_panel(hass)
        for svc in ("scan", "set_count", "save_product", "attach_barcode",
                    "list_products", "evaluate", "discard_provisional",
                    "delete_product", "attach_to_existing"):
            hass.services.async_remove(DOMAIN, svc)
        hass.data.get(DOMAIN, {}).pop("manager", None)
    return unloaded
