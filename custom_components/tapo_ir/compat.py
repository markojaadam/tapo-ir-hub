"""Compatibility imports for supported plugp100 releases."""
from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any

from plugp100.api.requests.tapo_request import TapoRequest
from plugp100.common.credentials import AuthCredential

_FACTORY_MODULES = (
    "plugp100.devices.factory",
    "plugp100.devices.device_factory",
    "plugp100.new.device_factory",
)


def _load_factory_module() -> ModuleType:
    """Load the factory module from every supported plugp100 layout."""
    for module_name in _FACTORY_MODULES:
        try:
            return import_module(module_name)
        except ModuleNotFoundError as err:
            if err.name != module_name and not module_name.startswith(f"{err.name}."):
                raise
    raise ImportError(
        "No supported plugp100 device factory was found; tried "
        + ", ".join(_FACTORY_MODULES)
    )


_factory_module = _load_factory_module()
connect: Any = _factory_module.connect
DeviceConnectConfiguration: Any = _factory_module.DeviceConnectConfiguration

__all__ = [
    "AuthCredential",
    "DeviceConnectConfiguration",
    "TapoRequest",
    "connect",
]
