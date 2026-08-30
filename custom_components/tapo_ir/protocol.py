"""Pure validation for Tapo and python-kasa protocol envelopes."""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any


class ProtocolResponseError(RuntimeError):
    """Raised when a protocol response contains a failed subrequest."""


def _protocol_code(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def validate_protocol_response(response: Any, method: str) -> None:
    """Raise when any relevant protocol envelope reports a failure."""
    if isinstance(response, Enum):
        code = _protocol_code(response)
        if code not in (None, 0, "0"):
            raise ProtocolResponseError(
                f"{method} failed with protocol error {code}"
            )
        return
    if isinstance(response, Mapping):
        for key in ("error_code", "errorCode"):
            if key in response:
                code = _protocol_code(response[key])
                if code not in (None, 0, "0"):
                    raise ProtocolResponseError(
                        f"{method} failed with protocol error {code}"
                    )
        for key in (
            method,
            "multipleRequest",
            "responses",
            "responseData",
            "result",
        ):
            if key in response:
                validate_protocol_response(response[key], method)
        return
    if isinstance(response, list):
        for item in response:
            validate_protocol_response(item, method)
