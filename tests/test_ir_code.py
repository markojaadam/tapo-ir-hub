"""Tests for safe IR code editing."""
from __future__ import annotations

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


ir_code = _load_module(
    "tapo_ir_code",
    ROOT / "custom_components" / "tapo_ir" / "ir_code.py",
)


class IrCodeTests(unittest.TestCase):
    """Verify exact round trips and conservative cleanup."""

    def test_round_trips_exact_values(self) -> None:
        encoded = ir_code.serialize_code(26, "1,2,3")
        self.assertEqual(encoded, '{"pwm":26,"pulse":"1,2,3"}')
        self.assertEqual(
            ir_code.parse_code_text(encoded),
            {"pwm": 26, "pulse": "1,2,3"},
        )

    def test_trims_only_explicit_zero_padding(self) -> None:
        self.assertEqual(
            ir_code.trim_numeric_silence("0,0,900,450,0"),
            "900,450",
        )

    def test_rejects_opaque_cleanup(self) -> None:
        with self.assertRaises(ir_code.IrCodeError):
            ir_code.trim_numeric_silence("encoded-pulse")

    def test_rejects_invalid_payloads(self) -> None:
        invalid = (
            "{}",
            '{"pwm":true,"pulse":"1,2"}',
            '{"pwm":26,"pulse":""}',
            "not-json",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(
                ir_code.IrCodeError
            ):
                ir_code.parse_code_text(value)


if __name__ == "__main__":
    unittest.main()
