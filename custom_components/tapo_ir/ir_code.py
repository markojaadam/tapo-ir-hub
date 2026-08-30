"""Pure parsing and conservative cleanup for editable IR codes."""
from __future__ import annotations

import json
import re
from typing import Any

CODE_MAX_LENGTH = 2_000_000
_NUMERIC_PULSE_RE = re.compile(r"^\s*-?\d+(?:[\s,;]+-?\d+)*\s*$")


class IrCodeError(ValueError):
    """Raised when editable IR code text is invalid."""


def parse_code_text(code_text: str, *, fallback_pwm: Any = None) -> dict[str, Any]:
    """Parse the exact JSON representation edited by the control card."""
    if len(code_text) > CODE_MAX_LENGTH:
        raise IrCodeError("IR code is too large")
    try:
        value = json.loads(code_text)
    except json.JSONDecodeError as err:
        raise IrCodeError(
            "IR code must be JSON with 'pwm' and 'pulse' fields"
        ) from err
    if not isinstance(value, dict):
        raise IrCodeError("IR code must be a JSON object")

    pwm = value.get("pwm", fallback_pwm)
    pulse = value.get("pulse")
    if isinstance(pwm, bool) or not isinstance(pwm, int) or pwm <= 0:
        raise IrCodeError("IR code 'pwm' must be a positive integer")
    if not isinstance(pulse, str) or not pulse:
        raise IrCodeError("IR code 'pulse' must be a non-empty string")
    if len(pulse) > CODE_MAX_LENGTH:
        raise IrCodeError("IR pulse data is too large")
    return {"pwm": pwm, "pulse": pulse}


def serialize_code(pwm: Any, pulse: Any) -> str:
    """Serialize a stored code without changing either stored value."""
    return json.dumps(
        {"pwm": pwm, "pulse": pulse},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def trim_numeric_silence(pulse: str) -> str:
    """Remove explicit zero-only padding from a numeric pulse sequence."""
    if not _NUMERIC_PULSE_RE.fullmatch(pulse):
        raise IrCodeError(
            "This code is not a numeric pulse sequence; it cannot be trimmed safely"
        )
    separator = "," if "," in pulse else (";" if ";" in pulse else " ")
    values = [part for part in re.split(r"[\s,;]+", pulse.strip()) if part]
    while values and int(values[0]) == 0:
        values.pop(0)
    while values and int(values[-1]) == 0:
        values.pop()
    if not values:
        raise IrCodeError("Trimming removed the entire pulse sequence")
    return separator.join(values)
