"""Experimental temporary learned-key transport for Mitsubishi max fan."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .mitsubishi import MitsubishiAcPulseError, promote_mitsubishi_ac_high_to_real_max

MITSUBISHI_MAX_TEMPLATE_LABEL = "HA Mitsubishi Max"


def _find_raw_key(
    remotes: list[dict[str, Any]], remote_device_id: str, key_name: str
) -> dict[str, Any]:
    for remote in remotes:
        if str(remote.get("device_id") or "") != remote_device_id:
            continue
        for key in remote.get("key_list") or []:
            if str(key.get("name") or "") == key_name:
                return deepcopy(key)
        break
    raise HomeAssistantError(
        f"Learned key {key_name!r} was not found on {remote_device_id!r}"
    )


def _editable_key(key: dict[str, Any]) -> dict[str, Any]:
    editable = deepcopy(key)
    editable.pop("enable", None)
    return editable


async def async_send_mitsubishi_real_max(
    coordinator: Any,
    remote_device_id: str,
    key_name: str,
) -> None:
    """Temporarily turn one learned HIGH frame into real MAX and fire it."""
    manager = coordinator.manager
    async with manager._lock:  # Same transaction lock used by learned-key edits.
        original = _find_raw_key(
            await coordinator.api.async_get_raw_devices(),
            remote_device_id,
            key_name,
        )
        pulse = original.get("pulse")
        if not isinstance(pulse, str) or not pulse:
            raise HomeAssistantError("The Mitsubishi template key has no waveform")
        try:
            max_pulse = promote_mitsubishi_ac_high_to_real_max(pulse)
        except MitsubishiAcPulseError as err:
            raise HomeAssistantError(str(err)) from err

        modified = _editable_key(original)
        modified["pulse"] = max_pulse
        restore = _editable_key(original)

        write_succeeded = False
        try:
            await coordinator.api.async_query_child(
                remote_device_id,
                "setKeyInfo",
                {"delete_key_list": [], "edit_key_list": [modified]},
            )
            write_succeeded = True
            await coordinator.api.async_fire(remote_device_id, key_name)
        finally:
            if write_succeeded:
                await coordinator.api.async_query_child(
                    remote_device_id,
                    "setKeyInfo",
                    {"delete_key_list": [], "edit_key_list": [restore]},
                )
