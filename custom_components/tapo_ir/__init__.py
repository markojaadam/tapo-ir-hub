"""Tapo IR Hub integration."""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .api import TapoIrApi, TapoIrAuthError, TapoIrError
from .const import (
    CONF_CONNECTION_MODE,
    CONF_HOST,
    CONF_NAME_OVERRIDES,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TPLINK_ENTRY_ID,
    CONF_USERNAME,
    CONNECTION_MODE_DIRECT,
    CONNECTION_MODE_SHARED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TapoIrCoordinator
from .frontend import async_register_frontend
from .shared_api import TapoIrSharedApi
from .websocket import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)


def _parse_overrides(raw: str | dict[str, Any] | None) -> dict[str, str]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        _LOGGER.warning("Ignoring malformed name_overrides")
        return {}
    if not isinstance(parsed, dict):
        _LOGGER.warning("Ignoring non-object name_overrides")
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the bundled utility card and admin websocket API."""
    await async_register_frontend(hass)
    async_register_websocket_api(hass)
    return True


def _build_api(
    hass: HomeAssistant,
    entry: ConfigEntry,
    overrides: dict[str, str],
) -> TapoIrApi | TapoIrSharedApi:
    mode = entry.data.get(CONF_CONNECTION_MODE, CONNECTION_MODE_DIRECT)
    if mode == CONNECTION_MODE_SHARED:
        return TapoIrSharedApi(
            hass,
            entry.data[CONF_TPLINK_ENTRY_ID],
            overrides,
        )
    return TapoIrApi(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        overrides=overrides,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Tapo IR hub."""
    overrides = _parse_overrides(entry.options.get(CONF_NAME_OVERRIDES))
    api = _build_api(hass, entry, overrides)
    try:
        await api.async_connect()
    except TapoIrAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except TapoIrError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = TapoIrCoordinator(
        hass,
        entry,
        api,
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _async_migrate_key_unique_ids(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_migrate_key_unique_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: TapoIrCoordinator,
) -> None:
    """Preserve existing entity IDs while moving to protocol-stable unique IDs."""
    registry = er.async_get(hass)
    for device in (coordinator.data or {}).values():
        for key in device["keys"]:
            old_unique_id = (
                f"{device['device_id']}_{key['legacy_slug']}"
            )
            key_identity = key.get("id")
            if key_identity in (None, -1):
                key_identity = key["name"]
            new_unique_id = f"{device['device_id']}_key_{key_identity}"
            old_entity_id = registry.async_get_entity_id(
                "button", DOMAIN, old_unique_id
            )
            new_entity_id = registry.async_get_entity_id(
                "button", DOMAIN, new_unique_id
            )
            if old_entity_id and not new_entity_id:
                registry.async_update_entity(
                    old_entity_id,
                    new_unique_id=new_unique_id,
                )


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Mark legacy credential entries as direct-mode entries."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_CONNECTION_MODE: CONNECTION_MODE_DIRECT,
            },
            version=2,
        )
        return True
    return entry.version == 2


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and resources owned by one config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: TapoIrCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
    return unloaded


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
