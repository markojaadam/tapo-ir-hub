"""Data coordinator and mutation facade for one Tapo IR hub."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import TapoIrApi, TapoIrAuthError, TapoIrError
from .const import DOMAIN
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

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            devices = await self.api.async_enumerate()
        except TapoIrAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TapoIrError as err:
            raise UpdateFailed(str(err)) from err
        self.last_scan = dt_util.utcnow()
        return {device["device_id"]: device for device in devices}

    async def async_fire(self, device_id: str, key_name: str) -> None:
        """Fire one stored key."""
        try:
            await self.api.async_fire(device_id, key_name)
        except TapoIrError as err:
            raise UpdateFailed(str(err)) from err

    async def async_control_ac(self, device_id: str, **changes: Any) -> None:
        """Send a complete AC state and update the optimistic cached state."""
        device = (self.data or {}).get(device_id)
        if device is None or "ac_state" not in device:
            raise UpdateFailed(f"AC remote {device_id!r} is not available")
        state = dict(device["ac_state"])
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
        try:
            await self.api.async_control_ac(device_id, current_state=state)
        except TapoIrError as err:
            raise UpdateFailed(str(err)) from err

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
