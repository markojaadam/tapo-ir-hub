"""Remote entities for each virtual IR profile."""
from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .button import child_device_info
from .coordinator import TapoIrCoordinator
from .naming import slugify

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a remote entity for each discovered profile."""
    coordinator: TapoIrCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_remotes() -> None:
        entities: list[TapoIrRemote] = []
        for device in (coordinator.data or {}).values():
            if device["device_id"] in known:
                continue
            known.add(device["device_id"])
            entities.append(TapoIrRemote(coordinator, device))
        if entities:
            async_add_entities(entities)

    _add_new_remotes()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_remotes))


class TapoIrRemote(CoordinatorEntity[TapoIrCoordinator], RemoteEntity):
    """A virtual remote that sends only explicitly requested stored keys."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:remote"
    _attr_is_on = True

    def __init__(
        self,
        coordinator: TapoIrCoordinator,
        device: dict,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device["device_id"]
        self._attr_unique_id = f"{self._device_id}_remote"
        self._attr_device_info = child_device_info(coordinator, device)

    @property
    def _device(self) -> dict | None:
        return (self.coordinator.data or {}).get(self._device_id)

    @property
    def available(self) -> bool:
        return super().available and self._device is not None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose readable command metadata without waveform payloads."""
        keys = (self._device or {}).get("keys", [])
        return {
            "commands": [key["name"] for key in keys],
            "button_names": {
                key["name"]: key["label"]
                for key in keys
            },
        }

    def _resolve_key(self, command: str) -> str:
        wanted = command.strip().casefold()
        wanted_slug = slugify(command)
        for key in (self._device or {}).get("keys", []):
            if wanted in {key["name"].casefold(), key["label"].casefold()}:
                return key["name"]
            if wanted_slug in {slugify(key["name"]), key["slug"]}:
                return key["name"]
        raise HomeAssistantError(
            f"Unknown IR command {command!r} for {self.entity_id}"
        )

    async def async_send_command(
        self, command: Iterable[str], **kwargs: object
    ) -> None:
        repeats = int(kwargs.get("num_repeats", 1))
        for requested in command:
            key_name = self._resolve_key(requested)
            for _repeat in range(max(1, repeats)):
                await self.coordinator.async_fire(self._device_id, key_name)

    async def async_turn_on(self, **kwargs: object) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
