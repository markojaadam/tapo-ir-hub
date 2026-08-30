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
    return _load(f"{PACKAGE}.manager", INTEGRATION / "manager.py")


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


if __name__ == "__main__":
    unittest.main()
