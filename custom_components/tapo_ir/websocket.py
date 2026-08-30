"""Admin-only websocket API used by the bundled IR control card."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import TapoIrError
from .const import (
    DOMAIN,
    WS_CREATE_REMOTE,
    WS_DELETE_KEY,
    WS_DELETE_REMOTE,
    WS_LEARN,
    WS_LIST,
    WS_RENAME_REMOTE,
    WS_SAVE_KEY,
    WS_STOP_LEARN,
)
from .coordinator import TapoIrCoordinator


def _coordinators(hass: HomeAssistant) -> list[TapoIrCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and isinstance(getattr(entry, "runtime_data", None), TapoIrCoordinator)
    ]


def _entry_coordinator(
    hass: HomeAssistant, entry_id: str
) -> TapoIrCoordinator:
    entry = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
        or not isinstance(getattr(entry, "runtime_data", None), TapoIrCoordinator)
    ):
        raise HomeAssistantError(f"Tapo IR hub entry {entry_id!r} is not loaded")
    return entry.runtime_data


def _remote_coordinator(
    hass: HomeAssistant, remote_device_id: str
) -> TapoIrCoordinator:
    for coordinator in _coordinators(hass):
        if remote_device_id in (coordinator.data or {}):
            return coordinator
    raise HomeAssistantError(
        f"IR remote {remote_device_id!r} is not available"
    )


def _send_error(
    connection: websocket_api.ActiveConnection,
    message_id: int,
    err: Exception,
) -> None:
    connection.send_error(message_id, "tapo_ir_error", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_LIST})
@websocket_api.async_response
async def ws_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all loaded hubs, remotes, and exact editable key codes."""
    hubs: list[dict[str, Any]] = []
    try:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if (
                entry.state is not ConfigEntryState.LOADED
                or not isinstance(
                    getattr(entry, "runtime_data", None), TapoIrCoordinator
                )
            ):
                continue
            coordinator: TapoIrCoordinator = entry.runtime_data
            hubs.append(
                {
                    "entry_id": entry.entry_id,
                    "hub_id": coordinator.hub_id,
                    "name": coordinator.hub_name,
                    "model": coordinator.api.hub_model,
                    "host": coordinator.api.host,
                    "connection_mode": entry.data.get("connection_mode", "direct"),
                    "remotes": await coordinator.manager.async_configuration(),
                }
            )
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"hubs": hubs})


_KEY_SCHEMA = vol.Schema(
    {
        vol.Required("label"): vol.All(cv.string, vol.Length(min=1, max=64)),
        vol.Required("code"): vol.All(
            cv.string, vol.Length(min=1, max=2_000_000)
        ),
        vol.Optional("trim_silence", default=False): cv.boolean,
    }
)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CREATE_REMOTE,
        vol.Required("entry_id"): cv.string,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=64)),
        vol.Required("keys"): vol.All(cv.ensure_list, [_KEY_SCHEMA]),
    }
)
@websocket_api.async_response
async def ws_create_remote(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a remote with its first key as one verified transaction."""
    try:
        coordinator = _entry_coordinator(hass, msg["entry_id"])
        result = await coordinator.manager.async_create_remote(
            msg["name"], msg["keys"]
        )
        await coordinator.async_refresh_after_mutation()
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_SAVE_KEY,
        vol.Required("remote_device_id"): cv.string,
        vol.Optional("key_reference"): cv.string,
        vol.Required("label"): vol.All(cv.string, vol.Length(min=1, max=64)),
        vol.Required("code"): vol.All(
            cv.string, vol.Length(min=1, max=2_000_000)
        ),
        vol.Optional("trim_silence", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_save_key(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update one button."""
    try:
        coordinator = _remote_coordinator(hass, msg["remote_device_id"])
        result = await coordinator.manager.async_save_key(
            msg["remote_device_id"],
            msg.get("key_reference"),
            msg["label"],
            msg["code"],
            msg["trim_silence"],
        )
        await coordinator.async_refresh_after_mutation()
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_RENAME_REMOTE,
        vol.Required("remote_device_id"): cv.string,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=64)),
    }
)
@websocket_api.async_response
async def ws_rename_remote(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename one remote."""
    try:
        coordinator = _remote_coordinator(hass, msg["remote_device_id"])
        result = await coordinator.manager.async_rename_remote(
            msg["remote_device_id"], msg["name"]
        )
        await coordinator.async_refresh_after_mutation()
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_DELETE_KEY,
        vol.Required("remote_device_id"): cv.string,
        vol.Required("key_reference"): cv.string,
        vol.Required("confirmation"): cv.string,
    }
)
@websocket_api.async_response
async def ws_delete_key(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one button after explicit confirmation."""
    if msg["confirmation"] != "DELETE":
        connection.send_error(
            msg["id"], "confirmation_required", 'Enter "DELETE" to continue'
        )
        return
    try:
        coordinator = _remote_coordinator(hass, msg["remote_device_id"])
        result = await coordinator.manager.async_delete_key(
            msg["remote_device_id"], msg["key_reference"]
        )
        await coordinator.async_refresh_after_mutation()
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_DELETE_REMOTE,
        vol.Required("remote_device_id"): cv.string,
        vol.Required("confirmation"): cv.string,
    }
)
@websocket_api.async_response
async def ws_delete_remote(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one remote after explicit confirmation."""
    if msg["confirmation"] != "DELETE":
        connection.send_error(
            msg["id"], "confirmation_required", 'Enter "DELETE" to continue'
        )
        return
    try:
        coordinator = _remote_coordinator(hass, msg["remote_device_id"])
        result = await coordinator.manager.async_delete_remote(
            msg["remote_device_id"]
        )
        await coordinator.async_refresh_after_mutation()
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_LEARN,
        vol.Optional("remote_device_id"): cv.string,
        vol.Optional("entry_id"): cv.string,
        vol.Optional("timeout", default=30): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=120)
        ),
    }
)
@websocket_api.async_response
async def ws_learn(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Capture one IR signal without saving or transmitting it."""
    try:
        if remote_device_id := msg.get("remote_device_id"):
            coordinator = _remote_coordinator(hass, remote_device_id)
        elif entry_id := msg.get("entry_id"):
            coordinator = _entry_coordinator(hass, entry_id)
        else:
            raise HomeAssistantError(
                "Learning requires a remote_device_id or entry_id"
            )
        result = await coordinator.manager.async_capture_signal(
            msg.get("remote_device_id"), msg["timeout"]
        )
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_STOP_LEARN})
@websocket_api.async_response
async def ws_stop_learn(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stop every active learning session owned by this integration."""
    stopped = 0
    try:
        for coordinator in _coordinators(hass):
            stopped += int(await coordinator.manager.async_stop_learning())
    except (HomeAssistantError, TapoIrError) as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], {"stopped": stopped})


def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register all card API commands once at integration setup."""
    for command in (
        ws_list,
        ws_create_remote,
        ws_save_key,
        ws_rename_remote,
        ws_delete_key,
        ws_delete_remote,
        ws_learn,
        ws_stop_learn,
    ):
        websocket_api.async_register_command(hass, command)
