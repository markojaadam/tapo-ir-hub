"""Sensor platform: hub-level diagnostics (device count + last scan)."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .button import hub_device_info
from .coordinator import TapoIrCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the hub diagnostic sensors."""
    coordinator: TapoIrCoordinator = entry.runtime_data
    async_add_entities(
        [
            TapoIrDeviceCountSensor(coordinator),
            TapoIrLastScanSensor(coordinator),
        ]
    )


class _TapoIrHubSensor(CoordinatorEntity[TapoIrCoordinator], SensorEntity):
    """Base for hub-attached diagnostic sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: TapoIrCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = hub_device_info(coordinator)


class TapoIrDeviceCountSensor(_TapoIrHubSensor):
    """Number of discovered child IR remotes, with a detailed attribute list."""

    _attr_translation_key = "discovered_devices"
    _attr_icon = "mdi:remote-tv"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: TapoIrCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.hub_id}_device_count"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, list]:
        devices = []
        for device in (self.coordinator.data or {}).values():
            devices.append(
                {
                    "name": device["name"],
                    "device_id": device["device_id"],
                    "key_count": len(device["keys"]),
                    "keys": [k["label"] for k in device["keys"]],
                }
            )
        return {"devices": devices}


class TapoIrLastScanSensor(_TapoIrHubSensor):
    """Timestamp of the most recent successful hub enumeration."""

    _attr_translation_key = "last_scan"
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: TapoIrCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.hub_id}_last_scan"

    @property
    def native_value(self):
        return self.coordinator.last_scan
