"""Tests for nested protocol failure handling."""
from __future__ import annotations

from enum import IntEnum
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protocol = _load_module(
    "tapo_ir_protocol",
    ROOT / "custom_components" / "tapo_ir" / "protocol.py",
)


class ErrorCode(IntEnum):
    SUCCESS = 0
    FAILED = -1


class ProtocolTests(unittest.TestCase):
    """Validate direct and batched response envelopes."""

    def test_accepts_successful_batch(self) -> None:
        protocol.validate_protocol_response(
            {
                "multipleRequest": {
                    "responses": [
                        {
                            "method": "sendIrCmdById",
                            "error_code": 0,
                            "result": {},
                        }
                    ]
                }
            },
            "sendIrCmdById",
        )

    def test_rejects_failed_batch(self) -> None:
        with self.assertRaises(protocol.ProtocolResponseError):
            protocol.validate_protocol_response(
                {
                    "multipleRequest": {
                        "responses": [
                            {
                                "method": "sendIrCmdById",
                                "error_code": -1003,
                            }
                        ]
                    }
                },
                "sendIrCmdById",
            )

    def test_handles_enum_error_codes(self) -> None:
        protocol.validate_protocol_response(
            {"sendIrCmdById": ErrorCode.SUCCESS},
            "sendIrCmdById",
        )
        with self.assertRaises(protocol.ProtocolResponseError):
            protocol.validate_protocol_response(
                {"sendIrCmdById": ErrorCode.FAILED},
                "sendIrCmdById",
            )


if __name__ == "__main__":
    unittest.main()
