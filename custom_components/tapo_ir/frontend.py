"""Serve and auto-load the bundled Tapo IR utility card."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import CONTROL_CARD_FILENAME, FRONTEND_URL, INTEGRATION_VERSION

_FRONTEND = Path(__file__).parent / "frontend"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register a cacheable module path and inject it into the HA frontend."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL,
                str(_FRONTEND),
                cache_headers=True,
            )
        ]
    )
    add_extra_js_url(
        hass,
        f"{FRONTEND_URL}/{CONTROL_CARD_FILENAME}?v={INTEGRATION_VERSION}",
    )
