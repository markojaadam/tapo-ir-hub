"""Redacted diagnostics for Tapo IR Hub."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from .coordinator import TapoIrCoordinator

_TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "credentials",
    "credentials_hash",
    "device_id",
    "host",
    "mac",
    "pulse",
}


def _remote_summary(
    devices: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return useful inventory without identifiers or IR waveforms."""
    return [
        {
            "name": device["name"],
            "model": device.get("model"),
            "key_count": len(device.get("keys", [])),
            "labels": [key["label"] for key in device.get("keys", [])],
            "label_sources": {
                source: sum(
                    key.get("label_source") == source
                    for key in device.get("keys", [])
                )
                for source in ("display_name", "protocol", "generated")
            },
            "has_ac_state": "ac_state" in device,
        }
        for device in devices.values()
    ]


def _exception_type(value: BaseException | None) -> str | None:
    """Return an actionable exception class without leaking message data."""
    return type(value).__name__ if value is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return a privacy-safe integration and parent-health snapshot."""
    coordinator = getattr(entry, "runtime_data", None)
    if not isinstance(coordinator, TapoIrCoordinator):
        return {
            "config_entry": async_redact_data(
                {
                    "title": entry.title,
                    "data": dict(entry.data),
                    "options": dict(entry.options),
                    "version": entry.version,
                    "state": entry.state.value,
                },
                _TO_REDACT,
            ),
            "coordinator": None,
            "parent_tplink": None,
            "remotes": [],
            "integration_domain": DOMAIN,
            "setup_incomplete": True,
        }
    parent: dict[str, Any] | None = None
    if coordinator.identifier_domain == "tplink":
        parent_entry_id = entry.data.get("tplink_entry_id")
        parent_entry = hass.config_entries.async_get_entry(parent_entry_id)
        parent_coordinator = getattr(
            getattr(parent_entry, "runtime_data", None),
            "parent_coordinator",
            None,
        )
        parent = {
            "entry_loaded": parent_entry is not None
            and parent_entry.state is ConfigEntryState.LOADED,
            "entry_state": (
                parent_entry.state.value if parent_entry is not None else "missing"
            ),
            "last_update_success": getattr(
                parent_coordinator, "last_update_success", None
            ),
            "last_exception_type": _exception_type(
                getattr(parent_coordinator, "last_exception", None)
            ),
        }

    return {
        "config_entry": async_redact_data(
            {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
                "version": entry.version,
            },
            _TO_REDACT,
        ),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception_type": _exception_type(
                coordinator.last_exception
            ),
            "last_scan": (
                coordinator.last_scan.isoformat()
                if coordinator.last_scan is not None
                else None
            ),
            "connection_mode": entry.data.get("connection_mode", "direct"),
            "remote_count": len(coordinator.data or {}),
        },
        "parent_tplink": parent,
        "remotes": _remote_summary(coordinator.data or {}),
        "integration_domain": DOMAIN,
    }
