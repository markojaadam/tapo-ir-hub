"""Pure Tapo AC state parsing and payload validation."""
from __future__ import annotations

from typing import Any

REQUIRED_AC_FIELDS = frozenset({"P", "M", "T", "S", "D"})
DEFAULT_IR_FREQUENCY = 38_000

_MITSUBISHI_FAN_TABLE_HIGH = "040B10034D5000034D5001034D5002034D5003"
_MITSUBISHI_FAN_TABLE_REAL_MAX = "040B10034D5000034D5001034D5002034D5004"


class AcStateError(ValueError):
    """Raised when a complete AC command cannot be built safely."""


def parse_ac_status(child: dict[str, Any]) -> dict[str, int]:
    """Parse the compact P/M/T/S/D status returned for AC remotes."""
    state: dict[str, int] = {}
    if isinstance(ac_status := child.get("ac_status"), str):
        for part in ac_status.split("_"):
            if len(part) < 2 or part[0] not in REQUIRED_AC_FIELDS:
                continue
            try:
                state[part[0]] = int(part[1:])
            except ValueError:
                continue

    fallbacks = {
        "P": child.get("on"),
        "M": child.get("ac_mode"),
        "T": child.get("current_temp"),
        "S": child.get("wind_speed"),
        "D": child.get("wind_direct"),
    }
    for key, value in fallbacks.items():
        if key not in state and value is not None:
            state[key] = int(bool(value)) if key == "P" else int(value)
    return state


def build_ac_payload(
    state: dict[str, int], *, pressed_fid: int | None = None
) -> dict[str, int]:
    """Build the native H110 sendIrCmdByStatus state payload."""
    missing = sorted(REQUIRED_AC_FIELDS - state.keys())
    if missing:
        raise AcStateError(
            "The hub has not reported a complete AC state; missing "
            + ", ".join(missing)
        )
    payload = {
        "power": int(bool(state["P"])),
        "mode": state["M"],
        "temp": state["T"],
        "wind_speed": state["S"],
        "wind_direct": state["D"],
    }
    if pressed_fid is not None:
        payload["pressed_fid"] = int(pressed_fid)
    return payload


def supports_mitsubishi_real_max(hex_data: Any) -> bool:
    """Return whether an AC profile has the verified Mitsubishi HIGH mapping."""
    return (
        isinstance(hex_data, str)
        and hex_data.upper().count(_MITSUBISHI_FAN_TABLE_HIGH) == 1
    )


def remap_mitsubishi_high_to_real_max(hex_data: str) -> str:
    """Remap Tapo HIGH (S3) to Mitsubishi's hidden native fan value 4."""
    normalized = hex_data.upper()
    count = normalized.count(_MITSUBISHI_FAN_TABLE_HIGH)
    if count != 1:
        raise AcStateError(
            "Expected exactly one verified Mitsubishi HIGH fan mapping; "
            f"found {count}"
        )
    return normalized.replace(
        _MITSUBISHI_FAN_TABLE_HIGH,
        _MITSUBISHI_FAN_TABLE_REAL_MAX,
        1,
    )


def build_ac_profile_payload(
    state: dict[str, int],
    *,
    hex_data: str,
    frequency: int = DEFAULT_IR_FREQUENCY,
    pressed_fid: int | None = None,
) -> dict[str, Any]:
    """Build a top-level sendIrCmdAc payload using an explicit AC profile."""
    payload: dict[str, Any] = {
        "frequency": int(frequency),
        "hexData": hex_data,
    }
    payload.update(build_ac_payload(state, pressed_fid=pressed_fid))
    return payload
