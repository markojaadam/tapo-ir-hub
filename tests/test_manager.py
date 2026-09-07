"""Transaction-level tests without a Home Assistant installation."""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "tapo_ir"
PACKAGE = "manager_test_pkg"


class HomeAssistantError(Exception):
    pass


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_manager():
    homeassistant = ModuleType("homeassistant")
    homeassistant.__path__ = []
    sys.modules["homeassistant"] = homeassistant
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules[core.__name__] = core
    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = HomeAssistantError
    sys.modules[exceptions.__name__] = exceptions
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    sys.modules[helpers.__name__] = helpers
    for name in ("device_registry", "entity_registry"):
        module = ModuleType(f"homeassistant.helpers.{name}")
        module.async_get = lambda hass: None
        sys.modules[module.__name__] = module
        setattr(helpers, name, module)

    package = ModuleType(PACKAGE)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[PACKAGE] = package
    const = ModuleType(f"{PACKAGE}.const")
    const.DOMAIN = "tapo_ir"
    sys.modules[const.__name__] = const
    _load(f"{PACKAGE}.naming", INTEGRATION / "naming.py")
    _load(f"{PACKAGE}.ir_code", INTEGRATION / "ir_code.py")
    _load(f"{PACKAGE}.errors", INTEGRATION / "errors.py")
    return _load(f"{PACKAGE}.manager", INTEGRATION / "manager.py")


with patch.dict(sys.modules):
    manager = _load_manager()


class _Bus:
    def async_fire(self, event, data):
        return None


class _Hass:
    bus = _Bus()


class _Api:
    def __init__(self) -> None:
        self.remotes = [
            {
                "device_id": "existing",
                "device_type": "SMART.TAPOREMOTE",
                "nickname": base64.b64encode(b"Existing").decode(),
                "category": "ir.remote",
                "model": "TV",
                "key_list": [],
            }
        ]

    async def async_get_raw_devices(self):
        return deepcopy(self.remotes)

    async def async_get_raw_remote(self, device_id):
        return deepcopy(
            next(
                item
                for item in self.remotes
                if item["device_id"] == device_id
            )
        )

    async def async_enumerate(self, *, include_codes=False):
        return [
            {
                "device_id": remote["device_id"],
                "name": "Existing",
                "model": remote.get("model"),
                "keys": [
                    {
                        "name": key["name"],
                        "id": key.get("id"),
                        "label": base64.b64decode(
                            key.get("display_name", "")
                        ).decode()
                        or key["name"],
                        "label_source": "display_name",
                        "slug": "key",
                        "legacy_slug": "key",
                        "icon": "mdi:remote",
                        "order": key.get("order", 1),
                        "type": key.get("type"),
                        "display_name": key.get("display_name"),
                        "pwm": key.get("pwm"),
                        "pulse": key.get("pulse"),
                    }
                    for key in remote.get("key_list", [])
                ],
            }
            for remote in self.remotes
        ]

    async def async_query_hub(self, method, params=None):
        if method != "addIrRemoteDevice":
            raise AssertionError(method)
        self.remotes.append(
            {
                **deepcopy(params),
                "device_id": "created",
                "key_list": [],
            }
        )
        return {"device_id": "created"}

    async def async_query_child(self, device_id, method, params=None):
        remote = next(
            (item for item in self.remotes if item["device_id"] == device_id),
            None,
        )
        if method == "deleteRemote":
            self.remotes = [
                item for item in self.remotes if item["device_id"] != device_id
            ]
            return {}
        if remote is None:
            raise AssertionError(f"Missing remote {device_id}")
        if method == "setKeyInfo":
            remote["key_list"] = deepcopy(params["edit_key_list"])
            return {}
        if method == "setDeviceInfo":
            remote["nickname"] = params["nickname"]
            # Simulate a concurrent vendor-app edit detected by the final snapshot.
            self.remotes[0]["model"] = "Changed concurrently"
            return {}
        raise AssertionError(method)


class ManagerTests(unittest.TestCase):
    """Verify failures after creation still roll back the created remote."""

    def test_delete_uses_canonical_key_and_direct_readback(self) -> None:
        api = _Api()
        api.remotes[0]["key_list"] = [
            {"name": "vendor-source", "display_name": base64.b64encode(b"Source").decode()},
            {"name": "power"},
        ]
        calls = []

        async def delete(device_id, method, params):
            calls.append((device_id, method, params))
            removed = {key["name"] for key in params["delete_key_list"]}
            api.remotes[0]["key_list"] = [
                key for key in api.remotes[0]["key_list"] if key["name"] not in removed
            ]
            return {}

        api.async_query_child = delete
        api.async_get_raw_devices = AsyncMock(side_effect=AssertionError("Use direct child readback"))
        transaction = manager.IRTransactionManager(_Hass(), api)
        result = asyncio.run(transaction.async_delete_key("existing", "Source"))
        self.assertEqual(result, {"deleted_key_name": "vendor-source", "verified": True})
        self.assertEqual(calls, [("existing", "setKeyInfo", {
            "delete_key_list": [{"name": "vendor-source"}], "edit_key_list": [],
        })])
        self.assertEqual(api.remotes[0]["key_list"], [{"name": "power"}])
        asyncio.run(transaction.async_delete_key("existing", "power"))
        self.assertEqual(len(api.remotes), 1)
        self.assertEqual(api.remotes[0]["key_list"], [])

    def test_delete_rejects_unverified_removal(self) -> None:
        key = {"name": "source"}
        for after in ({"key_list": [key]}, {}, {"key_list": None}):
            with self.subTest(after=after):
                api = _Api()
                api.async_get_raw_remote = AsyncMock(side_effect=[{"key_list": [key]}, after])
                api.async_query_child = AsyncMock(return_value={})
                transaction = manager.IRTransactionManager(_Hass(), api)
                with self.assertRaises(HomeAssistantError):
                    asyncio.run(transaction.async_delete_key("existing", "source"))
                api.async_query_child.assert_awaited_once()

    def test_delete_unknown_key_never_writes(self) -> None:
        api = _Api()
        api.async_query_child = AsyncMock()
        transaction = manager.IRTransactionManager(_Hass(), api)
        with self.assertRaises(HomeAssistantError):
            asyncio.run(transaction.async_delete_key("existing", "missing"))
        api.async_query_child.assert_not_awaited()

    def test_consistency_failure_removes_created_remote(self) -> None:
        api = _Api()
        transaction = manager.IRTransactionManager(_Hass(), api)
        with self.assertRaises(HomeAssistantError):
            asyncio.run(
                transaction.async_create_remote(
                    "New TV",
                    [{"label": "Power", "code": '{"pwm":26,"pulse":"1,2"}'}],
                )
            )
        self.assertEqual(
            [item["device_id"] for item in api.remotes],
            ["existing"],
        )

    def test_create_key_accepts_vendor_assigned_name(self) -> None:
        class VendorNamingApi(_Api):
            async def async_query_child(
                self, device_id, method, params=None
            ):
                if method == "setKeyInfo":
                    remote = next(
                        item
                        for item in self.remotes
                        if item["device_id"] == device_id
                    )
                    saved = deepcopy(params["edit_key_list"][0])
                    saved["name"] = "Ab3dE7xQ"
                    remote["key_list"].append(saved)
                    return {}
                return await super().async_query_child(
                    device_id, method, params
                )

        api = VendorNamingApi()
        transaction = manager.IRTransactionManager(_Hass(), api)
        result = asyncio.run(
            transaction.async_save_key(
                "existing",
                None,
                "Source",
                '{"pwm":26,"pulse":"1,2,3"}',
            )
        )
        self.assertEqual(result["key_name"], "Ab3dE7xQ")
        self.assertTrue(result["verified"])

    def test_create_key_verifies_when_hub_hides_saved_pulse(self) -> None:
        class HiddenPulseApi(_Api):
            async def async_query_child(
                self, device_id, method, params=None
            ):
                if method == "setKeyInfo":
                    remote = next(
                        item
                        for item in self.remotes
                        if item["device_id"] == device_id
                    )
                    saved = deepcopy(params["edit_key_list"][0])
                    saved.pop("pulse")
                    remote["key_list"].append(saved)
                    return {}
                return await super().async_query_child(
                    device_id, method, params
                )

        transaction = manager.IRTransactionManager(_Hass(), HiddenPulseApi())
        result = asyncio.run(
            transaction.async_save_key(
                "existing",
                None,
                "Source",
                '{"pwm":26,"pulse":"1,2,3"}',
            )
        )
        self.assertEqual(result["key_name"], "custom_source")
        self.assertEqual(result["code"], '{"pwm":26,"pulse":"1,2,3"}')
        self.assertTrue(result["verified"])
        self.assertFalse(result["waveform_verified"])

    def test_create_key_accepts_renamed_key_with_hidden_pulse(self) -> None:
        class RenamedHiddenPulseApi(_Api):
            async def async_query_child(
                self, device_id, method, params=None
            ):
                if method == "setKeyInfo":
                    remote = next(
                        item
                        for item in self.remotes
                        if item["device_id"] == device_id
                    )
                    saved = deepcopy(params["edit_key_list"][0])
                    saved["name"] = "Ab3dE7xQ"
                    saved.pop("pulse")
                    remote["key_list"].append(saved)
                    return {}
                return await super().async_query_child(
                    device_id, method, params
                )

        transaction = manager.IRTransactionManager(
            _Hass(), RenamedHiddenPulseApi()
        )
        result = asyncio.run(
            transaction.async_save_key(
                "existing",
                None,
                "Source",
                '{"pwm":26,"pulse":"1,2,3"}',
            )
        )
        self.assertEqual(result["key_name"], "Ab3dE7xQ")
        self.assertEqual(result["code"], '{"pwm":26,"pulse":"1,2,3"}')
        self.assertTrue(result["verified"])

    def test_creation_never_resolves_an_existing_key(self) -> None:
        key = {"id": 7, "name": "old", "display_name": manager._b64("Source"), "pwm": 26}
        with self.assertRaisesRegex(HomeAssistantError, "unambiguously"):
            manager._resolve_saved_key(
                {"key_list": [key]}, {"name": "custom_source"},
                {manager._key_identity(key)}, "Source",
                {"pwm": 26, "pulse": "1,2"}, creating=True,
            )

    def test_exact_protocol_reference_precedes_label(self) -> None:
        remote = {"key_list": [
            {"name": "wrong", "display_name": manager._b64("POWER")},
            {"name": "POWER", "display_name": manager._b64("On")},
        ]}
        self.assertEqual(manager._find_key(remote, "POWER")["name"], "POWER")

    def test_ambiguous_label_is_rejected(self) -> None:
        remote = {"key_list": [
            {"name": name, "display_name": manager._b64("Source")}
            for name in ("one", "two")
        ]}
        with self.assertRaisesRegex(HomeAssistantError, "ambiguous"):
            manager._find_key(remote, "Source")

    def test_invalid_initial_code_does_not_create_remote(self) -> None:
        api = _Api()
        with self.assertRaises(HomeAssistantError):
            asyncio.run(manager.IRTransactionManager(_Hass(), api).async_create_remote(
                "New", [{"label": "Source", "code": "null"}]
            ))
        self.assertEqual(len(api.remotes), 1)

    def test_unmarked_concurrent_remote_is_never_adopted(self) -> None:
        class ConcurrentApi(_Api):
            async def async_query_hub(self, method, params=None):
                self.remotes.append({"device_id": "someone-elses", "nickname": manager._b64("App")})
                return {}
            async def async_query_child(self, *args, **kwargs):
                raise AssertionError("Must not modify an unidentified remote")
        api = ConcurrentApi()
        with self.assertRaisesRegex(HomeAssistantError, "did not identify"):
            asyncio.run(manager.IRTransactionManager(_Hass(), api).async_create_remote(
                "New", [{"label": "Source", "code": '{"pwm":26,"pulse":"1,2"}'}]
            ))
        self.assertEqual(len(api.remotes), 2)

    def test_learning_cleans_up_start_and_stop_failures(self) -> None:
        for failed_method in ("startIrReceiveMode", "stopIrReceiveMode"):
            with self.subTest(method=failed_method):
                calls = []
                class LearningApi(_Api):
                    async def async_query_hub(self, method, params=None):
                        calls.append(method)
                        if method == failed_method:
                            raise HomeAssistantError("test failure")
                        return {"recv_status": 0, "pwm": 26, "pulse": "1,2"}
                transaction = manager.IRTransactionManager(_Hass(), LearningApi())
                with self.assertRaises(HomeAssistantError):
                    asyncio.run(transaction.async_capture_signal(None, 5))
                self.assertIn("stopIrReceiveMode", calls)
                self.assertIsNone(transaction._stop_learning)
                self.assertIsNone(transaction._learning_task)
                self.assertFalse(transaction._lock.locked())

    def test_learning_rejects_parallel_capture_and_shutdown_cleans_up(self) -> None:
        async def run():
            started = asyncio.Event()
            calls = []
            class LearningApi(_Api):
                async def async_query_hub(self, method, params=None):
                    calls.append(method)
                    if method == "getIrReceiveStatus":
                        started.set()
                        await asyncio.Event().wait()
                    return {}
            transaction = manager.IRTransactionManager(_Hass(), LearningApi())
            capture = asyncio.create_task(transaction.async_capture_signal(None, 5))
            await started.wait()
            with self.assertRaisesRegex(HomeAssistantError, "in progress"):
                await transaction.async_capture_signal(None, 5)
            await transaction.async_shutdown()
            self.assertTrue(capture.cancelled())
            self.assertEqual(calls.count("stopIrReceiveMode"), 1)
            self.assertIsNone(transaction._stop_learning)
        asyncio.run(run())

    def test_learning_waits_for_pulse_after_idle_success_status(self) -> None:
        class LearningApi(_Api):
            def __init__(self):
                super().__init__()
                self.polls = 0
            async def async_query_hub(self, method, params=None):
                if method == "getIrReceiveStatus":
                    self.polls += 1
                    return {"recv_status": 0, "pwm": 26, "pulse": "" if self.polls == 1 else "1,2"}
                return {}
        api = LearningApi()
        transaction = manager.IRTransactionManager(_Hass(), api)
        from unittest.mock import AsyncMock
        with patch.object(manager.asyncio, "sleep", new_callable=AsyncMock):
            result = asyncio.run(transaction.async_capture_signal(None, 5))
        self.assertEqual(api.polls, 2)
        self.assertEqual(result["code"], '{"pwm":26,"pulse":"1,2"}')

    def test_registry_cleanup_preserves_other_integrations(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock
        own = SimpleNamespace(entity_id="button.own", platform="tapo_ir", config_entry_id="ir")
        other = SimpleNamespace(entity_id="sensor.other", platform="tplink", config_entry_id="core")
        device = SimpleNamespace(id="registry-device", identifiers={("tplink", "remote")}, config_entries={"ir", "core"})
        devices = SimpleNamespace(devices={"registry-device": device}, async_update_device=Mock())
        entities = SimpleNamespace(async_remove=Mock())
        with patch.object(manager.dr, "async_get", return_value=devices), \
             patch.object(manager.er, "async_get", return_value=entities), \
             patch.object(manager.er, "async_entries_for_device", return_value=[own, other], create=True):
            asyncio.run(manager.IRTransactionManager(_Hass(), _Api(), "ir")._async_remove_registry_entries("remote"))
        entities.async_remove.assert_called_once_with("button.own")
        devices.async_update_device.assert_called_once_with("registry-device", remove_config_entry_id="ir")

if __name__ == "__main__":
    unittest.main()
