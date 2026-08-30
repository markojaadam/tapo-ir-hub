"""Regression tests for issue #1 plugp100 factory moves."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest

ROOT = Path(__file__).parents[1]
COMPAT_PATH = ROOT / "custom_components" / "tapo_ir" / "compat.py"
FACTORY_PATHS = (
    "plugp100.devices.factory",
    "plugp100.devices.device_factory",
    "plugp100.new.device_factory",
)


class _FactoryConfig:
    pass


async def _connect(config):
    return config


class CompatTests(unittest.TestCase):
    """Load compat.py against each historical package layout."""

    def tearDown(self) -> None:
        for name in list(sys.modules):
            if name.startswith("plugp100") or name.startswith("compat_under_test"):
                sys.modules.pop(name, None)

    @staticmethod
    def _package(name: str) -> ModuleType:
        module = ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
        return module

    def _install_common_stubs(self) -> None:
        self._package("plugp100")
        self._package("plugp100.api")
        self._package("plugp100.api.requests")
        request_module = ModuleType("plugp100.api.requests.tapo_request")
        request_module.TapoRequest = type("TapoRequest", (), {})
        sys.modules[request_module.__name__] = request_module
        self._package("plugp100.common")
        credentials_module = ModuleType("plugp100.common.credentials")
        credentials_module.AuthCredential = type("AuthCredential", (), {})
        sys.modules[credentials_module.__name__] = credentials_module

    def _load_for(self, factory_path: str, index: int):
        self._install_common_stubs()
        parent = factory_path.rsplit(".", 1)[0]
        if parent not in sys.modules:
            self._package(parent)
        factory_module = ModuleType(factory_path)
        factory_module.connect = _connect
        factory_module.DeviceConnectConfiguration = _FactoryConfig
        sys.modules[factory_path] = factory_module

        spec = importlib.util.spec_from_file_location(
            f"compat_under_test_{index}", COMPAT_PATH
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load compatibility module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_supports_all_known_factory_locations(self) -> None:
        for index, factory_path in enumerate(FACTORY_PATHS):
            with self.subTest(factory_path=factory_path):
                module = self._load_for(factory_path, index)
                self.assertIs(module.DeviceConnectConfiguration, _FactoryConfig)
                self.assertIs(module.connect, _connect)
                self.tearDown()


if __name__ == "__main__":
    unittest.main()
