"""Button entities for stored IR keys and hub rescans."""
from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import HUB_MODEL, MANUFACTURER, REMOTE_MODEL
from .coordinator import TapoIrCoordinator
from .mitsubishi_scratch import (
    MITSUBISHI_MAX_TEMPLATE_LABEL,
    async_send_mitsubishi_real_max,
)

PARALLEL_UPDATES = 1


def hub_device_info(coordinator: TapoIrCoordinator) -> DeviceInfo:
    """Return the registry identity for the physical hub."""
    return DeviceInfo(
        identifiers={(coordinator.identifier_domain, coordinator.hub_id)},
        name=coordinator.hub_name,
        manufacturer=MANUFACTURER,
        model=coordinator.api.hub_model or HUB_MODEL,
        sw_version=coordinator.api.hub_fw,
    )


def child_device_info(
    coordinator: TapoIrCoordinator, device: dict[str, Any]
) -> DeviceInfo:
    """Return the registry identity for one virtual remote."""
    namespace = coordinator.identifier_domain
    return DeviceInfo(
        identifiers={(namespace, device["device_id"])},
        name=device["name"],
        manufacturer=MANUFACTURER,
        model=device.get("model") or REMOTE_MODEL,
        via_device=(namespace, coordinator.hub_id),
    )


def key_unique_id(device_id: str, key: dict[str, Any]) -> str:
    """Build an ID from protocol identity rather than a mutable label."""
    identity = key.get("id")
    if identity in (None, -1):
        identity = key["name"]
    return f"{device_id}_key_{identity}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up key buttons and discover newly learned keys."""
    coordinator: TapoIrCoordinator = entry.runtime_data
    async_add_entities([TapoIrRescanButton(coordinator)])
    known: set[str] = set()

    @callback
    def _add_new_keys() -> None:
        new_entities: list[TapoIrKeyButton] = []
        for device in (coordinator.data or {}).values():
            for key in device["keys"]:
                unique_id = key_unique_id(device["device_id"], key)
                if unique_id in known:
                    continue
                known.add(unique_id)
                new_entities.append(
                    TapoIrKeyButton(
                        coordinator,
                        device,
                        key,
                        unique_id,
                    )
                )
        if new_entities:
            async_add_entities(new_entities)

    _add_new_keys()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_keys))


class TapoIrKeyButton(CoordinatorEntity[TapoIrCoordinator], ButtonEntity):
    """A stored IR key."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TapoIrCoordinator,
        device: dict[str, Any],
        key: dict[str, Any],
        unique_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device["device_id"]
        self._key_name = key["name"]
        self._attr_unique_id = unique_id
        self._attr_name = key["label"]
        self._attr_icon = key["icon"]
        self._attr_device_info = child_device_info(coordinator, device)

    def _current_key(self) -> dict[str, Any] | None:
        device = (self.coordinator.data or {}).get(self._device_id)
        if device is None:
            return None
        return next(
            (
                key
                for key in device["keys"]
                if key["name"] == self._key_name
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._current_key() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose identity metadata, never the large waveform."""
        key = self._current_key() or {}
        return {
            "protocol_name": self._key_name,
            "label_source": key.get("label_source"),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        if key := self._current_key():
            self._attr_name = key["label"]
            self._attr_icon = key["icon"]
        self.async_write_ha_state()

    async def async_press(self) -> None:
        key = self._current_key() or {}
        if key.get("label") == MITSUBISHI_MAX_TEMPLATE_LABEL:
            await async_send_mitsubishi_real_max(
                self.coordinator,
                self._device_id,
                self._key_name,
            )
            return
        await self.coordinator.async_fire(self._device_id, self._key_name)


class TapoIrRescanButton(
    CoordinatorEntity[TapoIrCoordinator], ButtonEntity
):
    """Force an immediate read-only refresh."""

    _attr_has_entity_name = True
    _attr_translation_key = "rescan_devices"
    _attr_icon = "mdi:magnify-scan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: TapoIrCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.hub_id}_rescan"
        self._attr_device_info = hub_device_info(coordinator)

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
