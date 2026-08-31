"""Helpers for migrating entities from the retired tplink_ir sidecar."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .naming import clean_text


def find_sidecar_entity(
    remote_id: str,
    key: Mapping[str, Any],
    candidates: Iterable[Any],
) -> Any | None:
    """Find one unambiguous sidecar entity for a normalized key."""
    prefix = f"{remote_id}_key_"
    remote_candidates = [
        candidate
        for candidate in candidates
        if str(getattr(candidate, "unique_id", "")).startswith(prefix)
    ]

    key_id = key.get("id")
    if key_id not in (None, -1):
        identity_prefix = f"{prefix}{key_id}_"
        identity_matches = [
            candidate
            for candidate in remote_candidates
            if str(getattr(candidate, "unique_id", "")).startswith(
                identity_prefix
            )
        ]
        if len(identity_matches) == 1:
            return identity_matches[0]

    wanted_label = clean_text(str(key.get("label", ""))).casefold()
    label_matches = [
        candidate
        for candidate in remote_candidates
        if clean_text(
            str(getattr(candidate, "original_name", "") or "")
        ).casefold()
        == wanted_label
    ]
    return label_matches[0] if len(label_matches) == 1 else None
