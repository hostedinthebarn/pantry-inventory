"""Websocket commands.

Every refusable write has a twin here. HA's REST service endpoint flattens ANY
handler exception to an opaque 500 - `ServiceValidationError` included - so the
reason a write was refused only survives over the websocket. Verified live
during the bugs_and_features build; do not rediscover it.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import connection
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    DEPARTMENT_SLUGS,
    DOMAIN,
    EVENT_ADJUST,
    EVENT_RECONCILE,
    EVENT_STOCK_IN,
    EVENT_USE_UP,
    POLICIES,
    PRODUCT_STATUSES,
)
from .coordinator import PantryError, PantryManager


def _manager(hass: HomeAssistant) -> PantryManager:
    return hass.data[DOMAIN]["manager"]


def _refusable(code: str):
    """Send the refusal MESSAGE back, which is the whole point of the twin."""
    def deco(func):
        async def wrapper(hass, conn, msg):
            try:
                await func(hass, conn, msg)
            except PantryError as err:
                conn.send_error(msg["id"], code, str(err))
        wrapper.__name__ = func.__name__
        return wrapper
    return deco


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/scan",
    vol.Required("code"): str,
    vol.Required("direction"): vol.In([EVENT_STOCK_IN, EVENT_USE_UP]),
    vol.Optional("source"): str,
})
@websocket_api.async_response
@_refusable("scan_failed")
async def ws_scan(hass, conn, msg):
    result = await _manager(hass).async_scan(
        msg["code"], msg["direction"], msg.get("source", "panel"))
    conn.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/set_count",
    vol.Required("product_id"): str,
    vol.Required("units"): vol.Coerce(int),
    vol.Optional("event_type", default=EVENT_ADJUST):
        vol.In([EVENT_ADJUST, EVENT_RECONCILE]),
    vol.Optional("source"): str,
})
@websocket_api.async_response
@_refusable("set_count_failed")
async def ws_set_count(hass, conn, msg):
    conn.send_result(msg["id"], await _manager(hass).async_set_count(
        msg["product_id"], msg["units"], msg.get("event_type", EVENT_ADJUST),
        msg.get("source", "panel")))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/save_product",
    vol.Required("product_id"): str,
    vol.Optional("name"): str,
    vol.Optional("unit_noun"): str,
    vol.Optional("initial_rate_estimate"): vol.Coerce(float),
    vol.Optional("threshold_days"): vol.Coerce(int),
    vol.Optional("policy"): vol.In(POLICIES),
    vol.Optional("threshold_units"): vol.Coerce(int),
    vol.Optional("purchase_quantity"): vol.Coerce(int),
    vol.Optional("department"): vol.In(list(DEPARTMENT_SLUGS) + [""]),
    vol.Optional("default_store"): cv.string,  # checked against the configured stores by the coordinator
    vol.Optional("status"): vol.In(PRODUCT_STATUSES),
})
@websocket_api.async_response
@_refusable("save_product_failed")
async def ws_save_product(hass, conn, msg):
    data = {k: v for k, v in msg.items() if k not in ("id", "type")}
    conn.send_result(msg["id"], await _manager(hass).async_save_product(data))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/attach_barcode",
    vol.Required("code"): str,
    vol.Required("product_id"): str,
    vol.Optional("units", default=1): vol.Coerce(int),
})
@websocket_api.async_response
@_refusable("attach_barcode_failed")
async def ws_attach_barcode(hass, conn, msg):
    conn.send_result(msg["id"], await _manager(hass).async_attach_barcode(
        msg["code"], msg["product_id"], msg.get("units", 1)))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/discard_provisional",
    vol.Required("product_id"): str,
})
@websocket_api.async_response
@_refusable("discard_failed")
async def ws_discard_provisional(hass, conn, msg):
    conn.send_result(msg["id"],
                     await _manager(hass).async_discard_provisional(msg["product_id"]))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/delete_product",
    vol.Required("product_id"): str,
    vol.Required("confirm_name"): str,
})
@websocket_api.async_response
@_refusable("delete_failed")
async def ws_delete_product(hass, conn, msg):
    conn.send_result(msg["id"], await _manager(hass).async_delete_product(
        msg["product_id"], msg["confirm_name"]))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/attach_to_existing",
    vol.Required("provisional_id"): str,
    vol.Required("target_id"): str,
    vol.Required("units"): vol.Coerce(int),
})
@websocket_api.async_response
@_refusable("attach_to_existing_failed")
async def ws_attach_to_existing(hass, conn, msg):
    conn.send_result(msg["id"], await _manager(hass).async_attach_to_existing(
        msg["provisional_id"], msg["target_id"], msg["units"]))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/dashboard"})
@callback
def ws_dashboard(hass, conn, msg):
    m = _manager(hass)
    conn.send_result(msg["id"], {
        "products": [m.state_for(p.product_id) for p in m.get_products()],
        "summary": m.summary(),
        "store_options": list(m.store_options),
    })


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_scan)
    websocket_api.async_register_command(hass, ws_set_count)
    websocket_api.async_register_command(hass, ws_save_product)
    websocket_api.async_register_command(hass, ws_attach_barcode)
    websocket_api.async_register_command(hass, ws_discard_provisional)
    websocket_api.async_register_command(hass, ws_delete_product)
    websocket_api.async_register_command(hass, ws_attach_to_existing)
    websocket_api.async_register_command(hass, ws_dashboard)
