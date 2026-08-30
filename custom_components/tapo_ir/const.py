"""Constants for the Tapo IR Hub integration."""
from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "tapo_ir"
INTEGRATION_VERSION: Final = "2.0.0"

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.REMOTE,
    Platform.SENSOR,
]

# Config entry data keys.
CONF_HOST: Final = "host"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_CONNECTION_MODE: Final = "connection_mode"
CONF_TPLINK_ENTRY_ID: Final = "tplink_entry_id"

CONNECTION_MODE_DIRECT: Final = "direct"
CONNECTION_MODE_SHARED: Final = "shared"
DIRECT_CONNECTION_OPTION: Final = "__direct__"

# Options keys.
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_NAME_OVERRIDES: Final = "name_overrides"

# Default re-query interval (seconds) for the background async task.
DEFAULT_SCAN_INTERVAL: Final = 300
MIN_SCAN_INTERVAL: Final = 30

# Manufacturer/model strings shown in the device registry.
MANUFACTURER: Final = "TP-Link"
HUB_MODEL: Final = "Tapo IR Hub (H1xx)"
REMOTE_MODEL: Final = "IR Remote profile"
IR_CATEGORY: Final = "ir.remote"

# Frontend and websocket API.
FRONTEND_URL: Final = "/tapo_ir_frontend"
CONTROL_CARD_FILENAME: Final = "tapo-ir-control-card.js"
WS_LIST: Final = "tapo_ir/remotes/list"
WS_SAVE_KEY: Final = "tapo_ir/key/save"
WS_CREATE_REMOTE: Final = "tapo_ir/remote/create"
WS_RENAME_REMOTE: Final = "tapo_ir/remote/rename"
WS_DELETE_KEY: Final = "tapo_ir/key/delete"
WS_DELETE_REMOTE: Final = "tapo_ir/remote/delete"
WS_LEARN: Final = "tapo_ir/learn"
WS_STOP_LEARN: Final = "tapo_ir/learn/stop"
