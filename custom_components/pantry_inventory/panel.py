"""Custom panel registration.

Registered as a module (embed_iframe defaults False), so it runs in HA's own
frontend document rather than an iframe. #0312 established that matters: an
iframe would need allow="camera" and would have failed for reasons unrelated to
the device.
"""

from __future__ import annotations

import os

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_API_PATH,
    PANEL_API_URL,
    PANEL_ICON,
    PANEL_NAME,
    PANEL_TITLE,
    PANEL_URL,
)


async def async_register_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    static_path = os.path.join(os.path.dirname(__file__), "panel", "dist")
    registered_key = f"{DOMAIN}_static_path_registered"
    if not hass.data.setdefault(registered_key, False):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_API_PATH, static_path, cache_headers=True)]
        )
        hass.data[registered_key] = True

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_NAME,
        frontend_url_path=PANEL_URL,
        # PANEL_API_URL carries ?v=VERSION - HA sends a 31-day cache header on
        # panel assets, so an unbumped version serves stale JS to the tablet.
        module_url=PANEL_API_URL,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
        config={},
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, PANEL_URL)
