"""Data coordinator and mutation facade for one Tapo IR hub."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .ac import (
    AcStateError,
    DEFAULT_IR_FREQUENCY,
    remap_mitsubishi_high_to_real_max,
    supports_mitsubishi_real_max,
)
from .api import TapoIrApi, TapoIrAuthError, TapoIrError
from .const import DOMAIN, REPAIR_SHARED_PARENT_UNAVAILABLE
from .manager import IRTransactionManager

_LOGGER = logging.getLogger(__name__)


class TapoIrCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll one hub while all writes remain serialized by its API adapter."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: TapoIrApi | Any,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ({api.host})",
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.api = api
        self.manager = IRTransactionManager(hass, api)
        self.last_scan: datetime | None = None
        self._mitsubishi_max_states: dict[str, dict[str, int]] = {}

    @property
    def hub_id(self) -> str:
        """Return the stable hub identifier."""
        return self.api.hub_id or self.api.host

    @property
    def hub_name(self) -> str:
        """Return the normalized hub name."""
        return self.api.hub_name

    @property
    def identifier_domain(self) -> str:
        """Return the registry namespace used by the owning integration."""
        return self.api.identifier_domain

    def is_mitsubishi_max_active(self, device_id: str) -> bool:
        """Return whether HA's optimistic state currently uses hidden MAX."""
        return device_id in self._mitsubishi_max_states

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            devices = await self.api.async_enumerate()
        except TapoIrAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TapoIrError as err:
            self._async_report_parent_unavailable()
            raise UpdateFailed(str(err)) from err
        self._async_clear_parent_unavailable()
        self.last_scan = dt_util.utcnow()

        updated = {device["device_id"]: device for device in devices}
        for device_id, state in list(self._mitsubishi_max_states.items()):
            device = updated.get(device_id)
            if device is None or not supports_mitsubishi_real_max(
                device.get("hex_data")
            ):
                self._mitsubishi_max_states.pop(device_id, None)
                continue
            shadowed = dict(device)
            shadowed["ac_state"] = dict(state)
            updated[device_id] = shadowed
        return updated

    @property
    def _repair_issue_id(self) -> str:
        return f"{REPAIR_SHARED_PARENT_UNAVAILABLE}_{self.config_entry.entry_id}"

    def _async_report_parent_unavailable(self) -> None:
        """Create one actionable issue for a failed shared parent."""
        if self.identifier_domain != "tplink":
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._repair_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=REPAIR_SHARED_PARENT_UNAVAILABLE,
            translation_placeholders={"hub": self.hub_name},
        )

    def _async_clear_parent_unavailable(self) -> None:
        """Clear the repair as soon as the parent hub recovers."""
        ir.async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)

    async def async_fire(self, device_id: str, key_name: str) -> None:
        """Fire one stored key."""
        try:
            await self.api.async_fire(device_id, key_name)
        except TapoIrError as err:
            raise UpdateFailed(str(err)) from err

    async def async_control_ac(
        self,
        device_id: str,
        *,
        pressed_fid: int | None = None,
        use_mitsubishi_max: bool | None = None,
        **changes: Any,
    ) -> None:
        """Send a complete AC state and update the optimistic cached state."""
        device = (self.data or {}).get(device_id)
        if device is None or "ac_state" not in device:
            raise UpdateFailed(f"AC remote {device_id!r} is not available")

        state = dict(
            self._mitsubishi_max_states.get(device_id, device["ac_state"])
        )
        mapping = {
            "power": ("P", lambda value: int(bool(value))),
            "mode": ("M", int),
            "temp": ("T", int),
            "wind_speed": ("S", int),
            "wind_direct": ("D", int),
        }
        for name, value in changes.items():
            if name not in mapping:
                raise UpdateFailed(f"Unsupported AC state field: {name}")
            key, converter = mapping[name]
            state[key] = converter(value)

        max_active = (
            self.is_mitsubishi_max_active(device_id)
            if use_mitsubishi_max is None
            else use_mitsubishi_max
        )

        try:
            if max_active:
                if state.get("S") != 3:
                    raise UpdateFailed(
                        "Mitsubishi MAX requires the Tapo HIGH fan slot (S3)"
                    )
                hex_data = device.get("hex_data")
                if not isinstance(hex_data, str):
                    raise UpdateFailed(
                        "The AC profile does not expose hexData required for MAX fan"
                    )
                try:
                    patched_hex_data = remap_mitsubishi_high_to_real_max(hex_data)
                except AcStateError as err:
                    raise UpdateFailed(str(err)) from err
                await self.api.async_control_ac_profile(
                    current_state=state,
                    hex_data=patched_hex_data,
                    frequency=int(device.get("frequency", DEFAULT_IR_FREQUENCY)),
                    pressed_fid=pressed_fid,
                )
            else:
                await self.api.async_control_ac(
                    device_id,
                    current_state=state,
                    pressed_fid=pressed_fid,
                )
        except TapoIrError as err:
            raise UpdateFailed(str(err)) from err

        if max_active:
            self._mitsubishi_max_states[device_id] = dict(state)
        else:
            self._mitsubishi_max_states.pop(device_id, None)

        updated = dict(self.data or {})
        updated_device = dict(device)
        updated_device["ac_state"] = state
        updated[device_id] = updated_device
        self.async_set_updated_data(updated)

    async def async_refresh_after_mutation(self) -> None:
        """Refresh entities after a verified hub mutation."""
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Close only resources owned by this integration."""
        await self.api.async_close()
