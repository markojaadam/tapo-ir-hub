"""Tests for the experimental Mitsubishi 144-bit fan transform."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mitsubishi = _load_module(
    "tapo_ir_mitsubishi",
    ROOT / "custom_components" / "tapo_ir" / "mitsubishi.py",
)

HIGH_STATE = bytes.fromhex(
    "23 CB 26 01 00 20 38 08 30 6B 00 00 00 00 00 00 00 10"
)
MAX_STATE = bytes.fromhex(
    "23 CB 26 01 00 20 38 08 30 6C 00 00 00 00 00 00 00 11"
)


def _encode_test_pulse(*states: bytes) -> str:
    values: list[int] = []
    for frame_index, state in enumerate(states):
        values.extend((3400, 1750))
        for byte in state:
            for bit_index in range(8):
                bit = (byte >> bit_index) & 1
                values.extend((450, 1300 if bit else 420))
        values.append(440)
        if frame_index != len(states) - 1:
            values.append(15500)
    return ",".join(str(value) for value in values)


class MitsubishiAcTests(unittest.TestCase):
    """Verify only the hidden fan value and checksum are changed."""

    def test_promotes_captured_high_frame_to_real_max(self) -> None:
        pulse = _encode_test_pulse(HIGH_STATE, HIGH_STATE)
        promoted = mitsubishi.promote_mitsubishi_ac_high_to_real_max(pulse)
        self.assertEqual(
            mitsubishi.decode_mitsubishi_ac_frames(promoted),
            [MAX_STATE, MAX_STATE],
        )

    def test_rejects_non_high_source(self) -> None:
        pulse = _encode_test_pulse(MAX_STATE)
        with self.assertRaisesRegex(
            mitsubishi.MitsubishiAcPulseError,
            "fan=3",
        ):
            mitsubishi.promote_mitsubishi_ac_high_to_real_max(pulse)

    def test_rejects_mismatched_repeats(self) -> None:
        different = bytearray(HIGH_STATE)
        different[7] ^= 1
        different[-1] = sum(different[:-1]) & 0xFF
        pulse = _encode_test_pulse(HIGH_STATE, bytes(different))
        with self.assertRaisesRegex(
            mitsubishi.MitsubishiAcPulseError,
            "do not match",
        ):
            mitsubishi.promote_mitsubishi_ac_high_to_real_max(pulse)


if __name__ == "__main__":
    unittest.main()
