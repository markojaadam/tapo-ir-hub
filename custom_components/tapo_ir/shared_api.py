"""Adapter for Home Assistant's already-authenticated core TP-Link session."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from .ac import AcStateError, build_ac_payload, build_ac_profile_payload
from .api import (
    TapoIrConnectionError,
    parse_child_devices,
)
from .const import IR_CATEGORY
from .naming import decode_vendor_text
from .protocol import ProtocolResponseError, validate_protocol_response


@dataclass(frozen=True, slots=True)
class SharedHub:
    """A loaded core TP-Link entry with at least one IR child."""

    entry_id: str
    hub_id: str
    name: str
    host: str


def _runtime_hub(entry: ConfigEntry) -> tuple[Any, Any]:
    runtime = getattr(entry, "runtime_data", None)
    coordinator = getattr(runtime, "parent_coordinator", None)
    hub = getattr(coordinator, "device", None)
    if coordinator is None or hub is None:
        raise TapoIrConnectionError(
            f"Core TP-Link entry {entry.entry_id} has no loaded parent device"
        )
    return coordinator, hub


def _ir_children(hub: Any) -> list[Any]:
    return [
        child
        for child in (getattr(hub, "children", None) or [])
        if (getattr(child, "_info", None) or {}).get("category") == IR_CATEGORY
    ]


def discover_shared_hubs(hass: HomeAssistant) -> list[SharedHub]:
    """Return loaded core TP-Link hubs that expose virtual IR remotes."""
    hubs: list[SharedHub] = []
    for entry in hass.config_entries.async_entries("tplink"):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        try:
            _, hub = _runtime_hub(entry)
        except TapoIrConnectionError:
            continue
        if not _ir_children(hub):
            continue
        hub_id = str(
            getattr(hub, "device_id", None)
            or getattr(hub, "mac", None)
            or entry.unique_id
            or entry.entry_id
        )
        name = (
            getattr(hub, "alias", None)
            or decode_vendor_text((getattr(hub, "_info", None) or {}).get("nickname"))
            or entry.title
        )
        hubs.append(
            SharedHub(
                entry_id=entry.entry_id,
                hub_id=hub_id,
                name=name,
                host=str(getattr(hub, "host", "")),
            )
        )
    return sorted(hubs, key=lambda hub: hub.name.casefold())


class TapoIrSharedApi:
    """Expose the direct API contract over the core TP-Link coordinator."""

    identifier_domain = "tplink"

    def __init__(
        self,
        hass: HomeAssistant,
        tplink_entry_id: str,
        overrides: dict[str, str] | None = None,
    ) -> None:
        self._hass = hass
        self._tplink_entry_id = tplink_entry_id
        self.overrides = overrides or {}
        self._coordinator: Any = None
        self._hub: Any = None
        self.hub_id: str | None = None
        self.hub_name = "Tapo IR Hub"
        self.hub_model: str | None = None
        self.hub_mac: str | None = None
        self.hub_fw: str | None = None

    @property
    def host(self) -> str:
        """Return the hub host."""
        return str(getattr(self._hub, "host", ""))

    def _entry(self) -> ConfigEntry:
        entry = self._hass.config_entries.async_get_entry(self._tplink_entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            raise TapoIrConnectionError(
                "The selected core TP-Link hub is not loaded"
            )
        return entry

    def _resolve(self) -> tuple[Any, Any]:
        self._coordinator, self._hub = _runtime_hub(self._entry())
        return self._coordinator, self._hub

    async def _async_refresh_parent(self) -> tuple[Any, Any]:
        """Refresh the owning coordinator and reject stale cached data."""
        coordinator, hub = self._resolve()
        try:
            await coordinator.async_request_refresh()
        except Exception as err:
            raise TapoIrConnectionError(
                f"Unable to refresh the shared TP-Link hub: {err}"
            ) from err
        if not coordinator.last_update_success:
            raise TapoIrConnectionError(
                f"Core TP-Link hub {self._entry().title!r} is unavailable"
            )
        return coordinator, hub

    async def async_connect(self) -> None:
        """Resolve the shared runtime and capture hub identity."""
        _, hub = await self._async_refresh_parent()
        info = getattr(hub, "_info", None) or {}
        self.hub_id = str(
            info.get("device_id")
            or getattr(hub, "device_id", None)
            or info.get("mac")
            or self._tplink_entry_id
        )
        self.hub_name = (
            getattr(hub, "alias", None)
            or decode_vendor_text(info.get("nickname"))
            or self._entry().title
        )
        self.hub_model = str(getattr(hub, "model", None) or info.get("model") or "")
        self.hub_mac = info.get("mac")
        self.hub_fw = (
            (getattr(hub, "hw_info", None) or {}).get("sw_ver")
            or info.get("fw_ver")
            or info.get("hw_ver")
        )

    async def async_get_raw_devices(self) -> list[dict[str, Any]]:
        """Refresh the shared coordinator and return raw IR child records."""
        _, hub = await self._async_refresh_parent()
        return [
            deepcopy(getattr(child, "_info", None) or {})
            for child in _ir_children(hub)
        ]

    async def async_enumerate(
        self, *, include_codes: bool = False
    ) -> list[dict[str, Any]]:
        """Return every normalized child IR remote."""
        children = await self.async_get_raw_devices()
        return parse_child_devices(
            {"child_device_list": children},
            self.overrides,
            include_codes=include_codes,
        )

    def _child(self, device_id: str) -> Any:
        _, hub = self._resolve()
        for child in _ir_children(hub):
            info = getattr(child, "_info", None) or {}
            if str(info.get("device_id") or getattr(child, "device_id", "")) == device_id:
                return child
        raise TapoIrConnectionError(f"IR remote {device_id!r} is not available")

    @staticmethod
    def _unwrap(response: Any, method: str) -> dict[str, Any]:
        if isinstance(response, dict) and method in response:
            response = response[method]
        return response if isinstance(response, dict) else {"result": response}

    async def async_query_hub(
        self, method: str, params: Any = None
    ) -> dict[str, Any]:
        """Run a hub method through the core integration's protocol object."""
        _, hub = self._resolve()
        try:
            response = await hub.protocol.query({method: params})
        except Exception as err:
            raise TapoIrConnectionError(
                f"Shared TP-Link hub request {method} failed: {err}"
            ) from err
        try:
            validate_protocol_response(response, method)
        except ProtocolResponseError as err:
            raise TapoIrConnectionError(str(err)) from err
        return self._unwrap(response, method)

    async def async_query_child(
        self,
        device_id: str,
        method: str,
        params: Any = None,
        *,
        batched: bool = False,
    ) -> dict[str, Any]:
        """Run a child method through the shared parent KLAP session."""
        child = self._child(device_id)
        query: dict[str, Any] = {method: params}
        if batched:
            query = {
                "multipleRequest": {
                    "requests": [{"method": method, "params": params}]
                }
            }
        try:
            response = await child.protocol.query(query)
        except Exception as err:
            raise TapoIrConnectionError(
                f"Shared TP-Link child request {method} failed: {err}"
            ) from err
        try:
            validate_protocol_response(response, method)
        except ProtocolResponseError as err:
            raise TapoIrConnectionError(str(err)) from err
        return self._unwrap(response, method)

    async def async_fire(self, device_id: str, key_name: str) -> dict[str, Any]:
        """Fire one stored IR key."""
        return await self.async_query_child(
            device_id,
            "sendIrCmdById",
            {"name": key_name},
            batched=True,
        )

    async def async_control_ac(
        self,
        device_id: str,
        *,
        current_state: dict[str, int],
        pressed_fid: int | None = None,
    ) -> dict[str, Any]:
        """Send one complete AC state through the shared session."""
        try:
            payload = build_ac_payload(current_state, pressed_fid=pressed_fid)
        except AcStateError as err:
            raise TapoIrConnectionError(str(err)) from err
        return await self.async_query_child(
            device_id, "sendIrCmdByStatus", payload, batched=True
        )

    async def async_control_ac_profile(
        self,
        *,
        current_state: dict[str, int],
        hex_data: str,
        frequency: int,
        pressed_fid: int | None = None,
    ) -> dict[str, Any]:
        """Send one complete AC state through an explicit transient profile."""
        try:
            payload = build_ac_profile_payload(
                current_state,
                hex_data=hex_data,
                frequency=frequency,
                pressed_fid=pressed_fid,
            )
        except AcStateError as err:
            raise TapoIrConnectionError(str(err)) from err
        return await self.async_query_hub("sendIrCmdAc", payload)

    async def async_close(self) -> None:
        """Leave the core integration-owned session open."""
