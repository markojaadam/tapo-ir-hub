"""Tapo IR Hub integration."""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import entity_sources
from homeassistant.helpers.typing import ConfigType

from .api import TapoIrApi, TapoIrAuthError, TapoIrError
from .const import (
    CONF_CONNECTION_MODE,
    CONF_HOST,
    CONF_LEGACY_ENTITY_IDS,
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
    REPAIR_SHARED_PARENT_UNAVAILABLE,
)
from .coordinator import TapoIrCoordinator
from .frontend import async_register_frontend
from .migration import find_sidecar_entity
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

    @callback
    def _async_parent_entry_changed(
        change: ConfigEntryChange,
        parent_entry: ConfigEntry,
    ) -> None:
        """Promptly resume dependent entries when a TP-Link hub recovers."""
        if (
            change is not ConfigEntryChange.UPDATED
            or parent_entry.domain != "tplink"
            or parent_entry.state is not ConfigEntryState.LOADED
        ):
            return
        for child_entry in hass.config_entries.async_entries(DOMAIN):
            if (
                child_entry.data.get(CONF_CONNECTION_MODE)
                == CONNECTION_MODE_SHARED
                and child_entry.data.get(CONF_TPLINK_ENTRY_ID)
                == parent_entry.entry_id
                and child_entry.state.recoverable
                and child_entry.state
                not in {
                    ConfigEntryState.LOADED,
                    ConfigEntryState.SETUP_IN_PROGRESS,
                }
            ):
                hass.config_entries.async_schedule_reload(
                    child_entry.entry_id
                )

    unsubscribe = async_dispatcher_connect(
        hass,
        SIGNAL_CONFIG_ENTRY_CHANGED,
        _async_parent_entry_changed,
    )
    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP,
        lambda _event: unsubscribe(),
    )
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
        if entry.data.get(CONF_CONNECTION_MODE) == CONNECTION_MODE_SHARED:
            ir.async_create_issue(
                hass,
                DOMAIN,
                f"{REPAIR_SHARED_PARENT_UNAVAILABLE}_{entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=REPAIR_SHARED_PARENT_UNAVAILABLE,
                translation_placeholders={"hub": entry.title},
            )
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = TapoIrCoordinator(
        hass,
        entry,
        api,
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()
    ir.async_delete_issue(
        hass,
        DOMAIN,
        f"{REPAIR_SHARED_PARENT_UNAVAILABLE}_{entry.entry_id}",
    )
    entry.runtime_data = coordinator

    _async_migrate_sidecar_entities(hass, entry, coordinator)
    _async_migrate_key_unique_ids(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _async_migrate_sidecar_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: TapoIrCoordinator,
) -> None:
    """Preserve sidecar entity IDs across the domain migration."""
    registry = er.async_get(hass)
    sidecar_entities = [
        entity
        for entity in registry.entities.values()
        if entity.platform == "tplink_ir"
        and entity.domain == "button"
    ]
    legacy_ids = dict(entry.data.get(CONF_LEGACY_ENTITY_IDS, {}))

    for device in (coordinator.data or {}).values():
        for key in device["keys"]:
            key_identity = key.get("id")
            if key_identity in (None, -1):
                key_identity = key["name"]
            new_unique_id = f"{device['device_id']}_key_{key_identity}"

            if new_unique_id not in legacy_ids:
                if sidecar := find_sidecar_entity(
                    device["device_id"],
                    key,
                    sidecar_entities,
                ):
                    legacy_ids[new_unique_id] = sidecar.entity_id

    if legacy_ids != entry.data.get(CONF_LEGACY_ENTITY_IDS, {}):
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_LEGACY_ENTITY_IDS: legacy_ids,
            },
        )

    for new_unique_id, legacy_entity_id in legacy_ids.items():
        legacy = registry.async_get(legacy_entity_id)
        current_entity_id = registry.async_get_entity_id(
            "button",
            DOMAIN,
            new_unique_id,
        )
        if legacy is not None and legacy.platform == "tplink_ir":
            if legacy_entity_id in entity_sources(hass):
                _LOGGER.info(
                    "Deferring migration of loaded sidecar entity %s",
                    legacy_entity_id,
                )
                continue
            if (
                current_entity_id is not None
                and current_entity_id != legacy_entity_id
            ):
                if current_entity_id in entity_sources(hass):
                    _LOGGER.info(
                        "Deferring migration while Tapo IR entity %s is loaded",
                        current_entity_id,
                    )
                    continue
                current = registry.async_get(current_entity_id)
                assert current is not None
                merged_aliases = list(legacy.aliases)
                merged_aliases.extend(
                    alias
                    for alias in current.aliases
                    if alias not in merged_aliases
                )
                registry.async_update_entity(
                    legacy_entity_id,
                    aliases=merged_aliases,
                    area_id=current.area_id or legacy.area_id,
                    categories={
                        **legacy.categories,
                        **current.categories,
                    },
                    disabled_by=(
                        current.disabled_by
                        if current.disabled_by is not None
                        else legacy.disabled_by
                    ),
                    entity_category=(
                        current.entity_category
                        if current.entity_category is not None
                        else legacy.entity_category
                    ),
                    hidden_by=(
                        current.hidden_by
                        if current.hidden_by is not None
                        else legacy.hidden_by
                    ),
                    icon=current.icon or legacy.icon,
                    labels=set(legacy.labels) | set(current.labels),
                    name=current.name or legacy.name,
                )
                registry.async_remove(current_entity_id)
                registry.async_update_entity_platform(
                    legacy_entity_id,
                    DOMAIN,
                    new_config_entry_id=entry.entry_id,
                    new_unique_id=new_unique_id,
                )
                continue
            try:
                registry.async_update_entity_platform(
                    legacy_entity_id,
                    DOMAIN,
                    new_config_entry_id=entry.entry_id,
                    new_unique_id=new_unique_id,
                )
            except ValueError:
                _LOGGER.info(
                    "Deferring migration of loaded sidecar entity %s",
                    legacy_entity_id,
                )
            continue
        if (
            legacy is None
            and current_entity_id is not None
            and current_entity_id != legacy_entity_id
        ):
            try:
                registry.async_update_entity(
                    current_entity_id,
                    new_entity_id=legacy_entity_id,
                )
            except ValueError:
                _LOGGER.warning(
                    "Cannot restore legacy entity ID %s because it is in use",
                    legacy_entity_id,
                )


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


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow removal only after a hub or remote is no longer reported."""
    coordinator = getattr(entry, "runtime_data", None)
    if not isinstance(coordinator, TapoIrCoordinator):
        return False
    active_ids = {coordinator.hub_id, *(coordinator.data or {})}
    integration_ids = {
        identifier
        for identifier in device_entry.identifiers
        if identifier[0] in {DOMAIN, coordinator.identifier_domain}
    }
    return bool(integration_ids) and all(
        identifier[1] not in active_ids for identifier in integration_ids
    )


async def async_remove_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove config-entry-scoped repair issues."""
    ir.async_delete_issue(
        hass,
        DOMAIN,
        f"{REPAIR_SHARED_PARENT_UNAVAILABLE}_{entry.entry_id}",
    )


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
