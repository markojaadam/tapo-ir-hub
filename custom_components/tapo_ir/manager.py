"""Transactional IR remote management with read-back verification."""
from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import secrets
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN
from .ir_code import (
    IrCodeError,
    parse_code_text,
    serialize_code,
    trim_numeric_silence,
)
from .naming import clean_text, slugify

EVENT_TRANSACTION = f"{DOMAIN}_transaction"
_CONFIG_FIELDS = (
    "device_id",
    "device_type",
    "nickname",
    "avatar",
    "category",
    "model",
    "brand",
    "remote_type",
    "remote_id",
    "frequency",
    "hexData",
    "key_sum",
    "downloaded_key_sum",
    "customize_key_sum",
    "key_list",
    "ac_status",
)


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _decode_b64(value: str | None) -> str:
    if not value:
        return ""
    try:
        return clean_text(base64.b64decode(value, validate=True).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return clean_text(value)


def _device_id(remote: Mapping[str, Any]) -> str:
    return str(remote.get("device_id") or "")


def _configuration(remote: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: deepcopy(remote[field])
        for field in _CONFIG_FIELDS
        if field in remote
    }


def _snapshot(remotes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        _device_id(remote): _configuration(remote)
        for remote in remotes
        if _device_id(remote)
    }


def _fingerprint(snapshot: Mapping[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_remote(
    remotes: list[dict[str, Any]], remote_device_id: str
) -> dict[str, Any]:
    for remote in remotes:
        if _device_id(remote) == remote_device_id:
            return remote
    raise HomeAssistantError(f"IR remote {remote_device_id!r} is not available")


def _find_key(remote: Mapping[str, Any], key_reference: str) -> dict[str, Any]:
    wanted = key_reference.casefold()
    for key in remote.get("key_list") or []:
        if str(key.get("name", "")).casefold() == wanted:
            return deepcopy(key)
        if _decode_b64(key.get("display_name")).casefold() == wanted:
            return deepcopy(key)
    raise HomeAssistantError(
        f"Key {key_reference!r} was not found on {_device_id(remote)}"
    )


def _new_key_name(remote: Mapping[str, Any], display_name: str) -> str:
    stem = slugify(display_name)
    existing = {
        str(key.get("name", "")).casefold()
        for key in remote.get("key_list") or []
    }
    candidate = f"custom_{stem}"
    suffix = 2
    while candidate.casefold() in existing:
        candidate = f"custom_{stem}_{suffix}"
        suffix += 1
    return candidate


def _clone_payload(source: Mapping[str, Any] | None, name: str) -> dict[str, Any]:
    source = source or {}
    return {
        "device_type": source.get("device_type", "SMART.TAPOREMOTE"),
        "nickname": _b64(name),
        "avatar": source.get("avatar", "remote"),
        "category": "ir.remote",
        "model": "Custom",
        "key_sum": 0,
        "brand": None,
        "key_list": [],
        "copy_device_id": None,
        "hexData": None,
        "remote_type": 1,
        "remote_id": None,
        "frequency": source.get("frequency"),
    }


def _find_created_id(response: Any) -> str | None:
    if isinstance(response, Mapping):
        if response.get("device_id"):
            return str(response["device_id"])
        for value in response.values():
            if found := _find_created_id(value):
                return found
    return None


class IRTransactionManager:
    """Serialize mutations and verify every saved result from the hub."""

    def __init__(self, hass: HomeAssistant, api: Any) -> None:
        self._hass = hass
        self.api = api
        self._lock = asyncio.Lock()
        self._stop_learning: asyncio.Event | None = None
        self._learning_remote_id: str | None = None

    def _audit(self, action: str, **data: Any) -> None:
        self._hass.bus.async_fire(
            EVENT_TRANSACTION,
            {"action": action, "timestamp": time.time(), **data},
        )

    async def _raw(self) -> list[dict[str, Any]]:
        return await self.api.async_get_raw_devices()

    async def async_configuration(self) -> list[dict[str, Any]]:
        """Return card-safe remotes with exact editable code strings."""
        remotes = await self.api.async_enumerate(include_codes=True)
        for remote in remotes:
            for key in remote["keys"]:
                pwm = key.pop("pwm")
                pulse = key.pop("pulse")
                if isinstance(pulse, str) and pulse:
                    key["code"] = serialize_code(pwm, pulse)
                    key["code_format"] = "waveform"
                else:
                    key["code"] = json.dumps(
                        {
                            "protocol_name": key["name"],
                            "pwm": pwm,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    key["code_format"] = "protocol_reference"
        return remotes

    async def async_create_remote(
        self,
        name: str,
        initial_keys: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Create a remote atomically; never leave a blank orphan behind."""
        name = clean_text(name)
        if not name or len(name) > 64:
            raise HomeAssistantError("Remote name must contain 1 to 64 characters")
        if not initial_keys:
            raise HomeAssistantError("A new remote requires at least one button")

        async with self._lock:
            before_raw = await self._raw()
            before = _snapshot(before_raw)
            source = before_raw[0] if before_raw else None
            marker = f" [HA-{secrets.token_hex(4)}]"
            temporary_name = f"{name[: 64 - len(marker)]}{marker}"
            response = await self.api.async_query_hub(
                "addIrRemoteDevice",
                _clone_payload(source, temporary_name),
            )
            response_id = _find_created_id(response)
            after_create = await self._raw()
            new_ids = set(_snapshot(after_create)) - set(before)
            marked_ids = {
                _device_id(remote)
                for remote in after_create
                if _device_id(remote) in new_ids
                and _decode_b64(remote.get("nickname")) == temporary_name
            }
            candidates = marked_ids | ({response_id} & new_ids)
            created_id = next(iter(candidates)) if len(candidates) == 1 else None
            if created_id is None and len(new_ids) == 1:
                created_id = new_ids.pop() if len(new_ids) == 1 else None
            if created_id is None:
                for candidate_id in marked_ids:
                    await self.api.async_query_child(candidate_id, "deleteRemote")
                if marked_ids:
                    await self._raw()
                raise HomeAssistantError(
                    f"Hub did not identify the newly created remote: {response!r}"
                )

            try:
                for key in initial_keys:
                    await self._save_key_locked(
                        created_id,
                        None,
                        key["label"],
                        key["code"],
                        bool(key.get("trim_silence", False)),
                    )
                current = _find_remote(await self._raw(), created_id)
                if not current.get("key_list"):
                    raise HomeAssistantError(
                        "The new remote did not retain its first button"
                    )
                await self.api.async_query_child(
                    created_id,
                    "setDeviceInfo",
                    {"nickname": _b64(name)},
                )
                renamed = _find_remote(await self._raw(), created_id)
                if _decode_b64(renamed.get("nickname")) != name:
                    raise HomeAssistantError(
                        "The new remote failed final-name verification"
                    )
                after = _snapshot(await self._raw())
                for device_id, configuration in before.items():
                    if after.get(device_id) != configuration:
                        raise HomeAssistantError(
                            f"Remote creation unexpectedly changed {device_id}"
                        )
            except Exception:
                try:
                    await self.api.async_query_child(created_id, "deleteRemote")
                    await self._raw()
                except Exception as cleanup_error:
                    raise HomeAssistantError(
                        f"Remote creation failed and cleanup also failed: {cleanup_error}"
                    ) from cleanup_error
                raise

            self._audit("create_remote", remote_device_id=created_id, name=name)
            return {
                "remote_device_id": created_id,
                "name": name,
                "key_count": len(initial_keys),
                "verified": True,
            }

    async def _save_key_locked(
        self,
        remote_device_id: str,
        key_reference: str | None,
        display_name: str,
        code_text: str,
        trim_silence: bool,
    ) -> dict[str, Any]:
        remotes = await self._raw()
        remote = _find_remote(remotes, remote_device_id)
        display_name = clean_text(display_name)
        if not display_name or len(display_name) > 64:
            raise HomeAssistantError("Button name must contain 1 to 64 characters")

        if key_reference:
            key = _find_key(remote, key_reference)
            action = "update_key"
        else:
            key = {
                "name": _new_key_name(remote, display_name),
                "id": -1,
                "icon": "",
                "order": len(remote.get("key_list") or []) + 1,
                "type": "",
            }
            action = "create_key"

        try:
            code = parse_code_text(code_text, fallback_pwm=key.get("pwm"))
            if trim_silence:
                code["pulse"] = trim_numeric_silence(code["pulse"])
        except IrCodeError as err:
            raise HomeAssistantError(str(err)) from err
        key.update(
            {
                "id": -1,
                "display_name": _b64(display_name),
                "pwm": code["pwm"],
                "pulse": code["pulse"],
            }
        )
        key.pop("enable", None)
        await self.api.async_query_child(
            remote_device_id,
            "setKeyInfo",
            {"delete_key_list": [], "edit_key_list": [key]},
        )

        saved_remote = _find_remote(await self._raw(), remote_device_id)
        saved = _find_key(saved_remote, str(key["name"]))
        if (
            saved.get("pwm") != code["pwm"]
            or str(saved.get("pulse")) != code["pulse"]
            or _decode_b64(saved.get("display_name")) != display_name
        ):
            raise HomeAssistantError(
                f"Button {key['name']!r} failed read-back verification"
            )
        self._audit(
            action,
            remote_device_id=remote_device_id,
            key_name=key["name"],
        )
        return {
            "remote_device_id": remote_device_id,
            "key_name": key["name"],
            "display_name": display_name,
            "code": serialize_code(saved.get("pwm"), saved.get("pulse")),
            "verified": True,
        }

    async def async_save_key(
        self,
        remote_device_id: str,
        key_reference: str | None,
        display_name: str,
        code_text: str,
        trim_silence: bool = False,
    ) -> dict[str, Any]:
        """Create or update a key and verify its exact waveform."""
        async with self._lock:
            return await self._save_key_locked(
                remote_device_id,
                key_reference,
                display_name,
                code_text,
                trim_silence,
            )

    async def async_capture_signal(
        self, remote_device_id: str | None, timeout: int
    ) -> dict[str, Any]:
        """Capture one signal without saving or transmitting it."""
        if not 5 <= timeout <= 120:
            raise HomeAssistantError("Learning timeout must be 5 to 120 seconds")
        async with self._lock:
            if remote_device_id is not None:
                _find_remote(await self._raw(), remote_device_id)
            stop_event = self._stop_learning = asyncio.Event()
            self._learning_remote_id = remote_device_id
            await self.api.async_query_hub("startIrReceiveMode")
            try:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if stop_event.is_set():
                        raise HomeAssistantError("IR learning was stopped")
                    status = await self.api.async_query_hub("getIrReceiveStatus")
                    receive_status = status.get("recv_status")
                    pwm = status.get("pwm")
                    pulse = status.get("pulse")
                    if receive_status == 0 and isinstance(pwm, int) and pulse:
                        code = serialize_code(pwm, str(pulse))
                        self._audit(
                            "capture_signal",
                            remote_device_id=remote_device_id,
                            pwm=pwm,
                        )
                        return {"code": code, "verified": True}
                    if receive_status == -2:
                        raise HomeAssistantError(
                            "The hub reported an invalid or unusable IR signal"
                        )
                    await asyncio.sleep(0.5)
                raise HomeAssistantError(
                    f"No IR signal was received within {timeout} seconds"
                )
            finally:
                await self.api.async_query_hub("stopIrReceiveMode")
                self._stop_learning = None
                self._learning_remote_id = None

    async def async_stop_learning(self) -> bool:
        """Stop an active capture as soon as the protocol lock is available."""
        if self._stop_learning is None:
            return False
        self._stop_learning.set()
        await self.api.async_query_hub("stopIrReceiveMode")
        return True

    async def async_rename_remote(
        self, remote_device_id: str, name: str
    ) -> dict[str, Any]:
        """Rename a remote and verify the new nickname."""
        name = clean_text(name)
        if not name or len(name) > 64:
            raise HomeAssistantError("Remote name must contain 1 to 64 characters")
        async with self._lock:
            await self.api.async_query_child(
                remote_device_id, "setDeviceInfo", {"nickname": _b64(name)}
            )
            current = _find_remote(await self._raw(), remote_device_id)
            if _decode_b64(current.get("nickname")) != name:
                raise HomeAssistantError("Remote rename failed read-back verification")
            self._audit("rename_remote", remote_device_id=remote_device_id, name=name)
            return {"remote_device_id": remote_device_id, "name": name, "verified": True}

    async def async_delete_key(
        self, remote_device_id: str, key_reference: str
    ) -> dict[str, Any]:
        """Delete one key and verify it is gone."""
        async with self._lock:
            remote = _find_remote(await self._raw(), remote_device_id)
            key = _find_key(remote, key_reference)
            await self.api.async_query_child(
                remote_device_id,
                "setKeyInfo",
                {
                    "delete_key_list": [{"name": key["name"]}],
                    "edit_key_list": [],
                },
            )
            current = _find_remote(await self._raw(), remote_device_id)
            if any(
                item.get("name") == key["name"]
                for item in current.get("key_list") or []
            ):
                raise HomeAssistantError("Deleted button remains in hub read-back")
            self._audit(
                "delete_key",
                remote_device_id=remote_device_id,
                key_name=key["name"],
            )
            return {"deleted_key_name": key["name"], "verified": True}

    async def async_delete_remote(self, remote_device_id: str) -> dict[str, Any]:
        """Delete one remote and preserve every other remote exactly."""
        async with self._lock:
            before = _snapshot(await self._raw())
            _find_remote(list(before.values()), remote_device_id)
            await self.api.async_query_child(remote_device_id, "deleteRemote")
            after = _snapshot(await self._raw())
            if remote_device_id in after:
                raise HomeAssistantError("Deleted remote remains in hub read-back")
            for device_id, configuration in before.items():
                if device_id != remote_device_id and after.get(device_id) != configuration:
                    raise HomeAssistantError(
                        f"Remote deletion unexpectedly changed {device_id}"
                    )
            await self._async_remove_registry_entries(remote_device_id)
            self._audit("delete_remote", remote_device_id=remote_device_id)
            return {"deleted_device_id": remote_device_id, "verified": True}

    async def _async_remove_registry_entries(self, remote_device_id: str) -> None:
        device_registry = dr.async_get(self._hass)
        entity_registry = er.async_get(self._hass)
        identifiers = {
            (DOMAIN, remote_device_id),
            ("tplink", remote_device_id),
        }
        for device in list(device_registry.devices.values()):
            if not identifiers.intersection(device.identifiers):
                continue
            for entry in list(
                er.async_entries_for_device(entity_registry, device.id)
            ):
                entity_registry.async_remove(entry.entity_id)
                self._hass.states.async_remove(entry.entity_id)
            device_registry.async_remove_device(device.id)
