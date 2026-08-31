"""Tests for legacy sidecar entity matching."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "tapo_ir"
PACKAGE = "migration_test_pkg"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = ModuleType(PACKAGE)
package.__path__ = [str(INTEGRATION)]
sys.modules[PACKAGE] = package
_load(f"{PACKAGE}.naming", INTEGRATION / "naming.py")
migration = _load(f"{PACKAGE}.migration", INTEGRATION / "migration.py")


class MigrationTests(unittest.TestCase):
    """Match numeric and custom sidecar keys without guessing."""

    def test_matches_stable_numeric_key_identity(self) -> None:
        candidates = [
            SimpleNamespace(
                unique_id="remote_key_1_power",
                entity_id="button.old_power",
                original_name="Power",
            )
        ]
        match = migration.find_sidecar_entity(
            "remote",
            {"id": 1, "name": "POWER", "label": "Power"},
            candidates,
        )
        self.assertEqual(match.entity_id, "button.old_power")

    def test_matches_custom_key_by_unique_label(self) -> None:
        candidates = [
            SimpleNamespace(
                unique_id="remote_key_-1_power",
                entity_id="button.pc_monitors_power",
                original_name="Power",
            ),
            SimpleNamespace(
                unique_id="remote_key_-1_ok",
                entity_id="button.pc_monitors_ok",
                original_name="Ok",
            ),
        ]
        match = migration.find_sidecar_entity(
            "remote",
            {"id": -1, "name": "5W889py8", "label": "Power"},
            candidates,
        )
        self.assertEqual(match.entity_id, "button.pc_monitors_power")

    def test_refuses_ambiguous_label(self) -> None:
        candidates = [
            SimpleNamespace(
                unique_id=f"remote_key_-1_power_{index}",
                entity_id=f"button.power_{index}",
                original_name="Power",
            )
            for index in range(2)
        ]
        self.assertIsNone(
            migration.find_sidecar_entity(
                "remote",
                {"id": -1, "name": "generated", "label": "Power"},
                candidates,
            )
        )


if __name__ == "__main__":
    unittest.main()
