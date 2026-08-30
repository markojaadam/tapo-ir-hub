"""Tests for entity-name normalization."""
from __future__ import annotations

import base64
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


naming = _load_module(
    "tapo_ir_naming",
    ROOT / "custom_components" / "tapo_ir" / "naming.py",
)


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


class NamingTests(unittest.TestCase):
    """Validate labels observed on real H110 remote profiles."""

    def test_decodes_normal_vendor_label(self) -> None:
        self.assertEqual(naming.decode_vendor_text(_encoded("Power")), "Power")

    def test_prefers_protocol_name_over_embedded_metadata(self) -> None:
        self.assertEqual(
            naming.humanize_key_label("0", _encoded("0\x00tp"), 1),
            ("0", "protocol"),
        )

    def test_expands_navigation_and_temperature_names(self) -> None:
        self.assertEqual(
            naming.humanize_key_label("NAVIGATE_UP", _encoded("NAVI"), 1)[0],
            "Up",
        )
        self.assertEqual(
            naming.humanize_key_label("TEMP+", _encoded("TEMP+"), 2)[0],
            "Temperature Up",
        )

    def test_replaces_opaque_key_identifier(self) -> None:
        self.assertEqual(
            naming.humanize_key_label("ANfaXW0W", "ANfaXW0W", 4),
            ("Unlabeled Button 4", "generated"),
        )

    def test_preserves_known_acronyms(self) -> None:
        self.assertEqual(
            naming.humanize_key_label("USB", _encoded("USB"), 1)[0],
            "USB",
        )
        self.assertEqual(
            naming.humanize_key_label("OK", _encoded("OK"), 1)[0],
            "OK",
        )

    def test_humanizes_bad_remote_nickname(self) -> None:
        self.assertEqual(
            naming.humanize_remote_name(
                "802DF972AE1F030B0006",
                _encoded("5W889py8"),
                ["5W889py8"],
            ),
            "IR Remote 0006",
        )


if __name__ == "__main__":
    unittest.main()
