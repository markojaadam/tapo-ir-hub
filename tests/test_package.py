"""Dependency-free packaging and safety checks."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "tapo_ir"


class PackageTests(unittest.TestCase):
    """Keep bundled metadata and frontend safety boundaries aligned."""

    def test_versions_match(self) -> None:
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        const_text = (INTEGRATION / "const.py").read_text()
        card_text = (
            INTEGRATION / "frontend" / "tapo-ir-control-card.js"
        ).read_text()
        const_version = re.search(
            r'INTEGRATION_VERSION: Final = "([^"]+)"', const_text
        )
        card_version = re.search(
            r'CARD_VERSION = "([^"]+)"', card_text
        )
        self.assertIsNotNone(const_version)
        self.assertIsNotNone(card_version)
        self.assertEqual(manifest["version"], const_version.group(1))
        self.assertEqual(manifest["version"], card_version.group(1))

    def test_english_translation_matches_source(self) -> None:
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        english = json.loads(
            (INTEGRATION / "translations" / "en.json").read_text()
        )
        self.assertEqual(strings, english)

    def test_control_card_has_no_transmit_path(self) -> None:
        card_text = (
            INTEGRATION / "frontend" / "tapo-ir-control-card.js"
        ).read_text()
        for forbidden in (
            "sendIrCmdById",
            "sendIrCmdByStatus",
            "remote.send_command",
            ".callService(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, card_text)


if __name__ == "__main__":
    unittest.main()
