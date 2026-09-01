"""Tests for conservative AC state handling."""
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


ac = _load_module(
    "tapo_ir_ac",
    ROOT / "custom_components" / "tapo_ir" / "ac.py",
)


class AcTests(unittest.TestCase):
    """Never fabricate unknown fields in a physical AC command."""

    def test_parses_complete_status(self) -> None:
        self.assertEqual(
            ac.parse_ac_status({"ac_status": "P1_M0_T22_S1_D0"}),
            {"P": 1, "M": 0, "T": 22, "S": 1, "D": 0},
        )

    def test_builds_native_h110_payload(self) -> None:
        self.assertEqual(
            ac.build_ac_payload({"P": 1, "M": 0, "T": 22, "S": 1, "D": 0}),
            {
                "power": 1,
                "mode": 0,
                "temp": 22,
                "wind_speed": 1,
                "wind_direct": 0,
            },
        )

    def test_builds_payload_with_pressed_fid(self) -> None:
        self.assertEqual(
            ac.build_ac_payload(
                {"P": 1, "M": 0, "T": 22, "S": 1, "D": 0},
                pressed_fid=6,
            ),
            {
                "power": 1,
                "mode": 0,
                "temp": 22,
                "wind_speed": 1,
                "wind_direct": 0,
                "pressed_fid": 6,
            },
        )

    def test_builds_power_off_as_integer(self) -> None:
        self.assertEqual(
            ac.build_ac_payload({"P": 0, "M": 0, "T": 22, "S": 1, "D": 0})[
                "power"
            ],
            0,
        )

    def test_rejects_incomplete_state(self) -> None:
        with self.assertRaises(ac.AcStateError):
            ac.build_ac_payload({"P": 1, "M": 0, "T": 22})

    def test_detects_verified_mitsubishi_max_profile(self) -> None:
        profile = (
            "AA"
            "040B10034D5000034D5001034D5002034D5003"
            "BB"
        )
        self.assertTrue(ac.supports_mitsubishi_real_max(profile))

    def test_remaps_high_slot_without_changing_profile_length(self) -> None:
        profile = (
            "AA"
            "040B10034D5000034D5001034D5002034D5003"
            "BB"
        )
        patched = ac.remap_mitsubishi_high_to_real_max(profile)

        self.assertEqual(len(patched), len(profile))
        self.assertIn(
            "040B10034D5000034D5001034D5002034D5004",
            patched,
        )
        self.assertNotIn(
            "040B10034D5000034D5001034D5002034D5003",
            patched,
        )

    def test_rejects_unknown_profile_for_max_remap(self) -> None:
        with self.assertRaises(ac.AcStateError):
            ac.remap_mitsubishi_high_to_real_max("DEADBEEF")

    def test_builds_send_ir_cmd_ac_payload_with_s3(self) -> None:
        payload = ac.build_ac_profile_payload(
            {"P": 1, "M": 3, "T": -1, "S": 3, "D": 0},
            hex_data="DEADBEEF",
            pressed_fid=5,
        )
        self.assertEqual(
            payload,
            {
                "frequency": 38000,
                "hexData": "DEADBEEF",
                "power": 1,
                "mode": 3,
                "temp": -1,
                "wind_speed": 3,
                "wind_direct": 0,
                "pressed_fid": 5,
            },
        )


if __name__ == "__main__":
    unittest.main()
