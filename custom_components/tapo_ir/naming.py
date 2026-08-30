"""Pure helpers for safe, readable IR remote and key names."""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata

_OPAQUE_ID_RE = re.compile(r"^(?=.{8}$)(?=.*[A-Z])(?=.*[a-z])(?=.*\d)[A-Za-z0-9]+$")
_BASE64_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/]{4,}={0,2}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")

_KEY_ALIASES = {
    "HOMEPAGE": "Home",
    "HOTKEYS": "Hotkeys",
    "IMAGE EFFECTS": "Picture",
    "NAVIGATE_DOWN": "Down",
    "NAVIGATE_LEFT": "Left",
    "NAVIGATE_RIGHT": "Right",
    "NAVIGATE_UP": "Up",
    "ONE TOUCH": "One Touch",
    "SCREEN ENLARGING": "Aspect Ratio",
    "SOUND EFFECTS": "Sound Mode",
    "SOUND PROJECT": "Sound Mode",
    "TEMP-": "Temperature Down",
    "TEMP+": "Temperature Up",
    "VOL-": "Volume Down",
    "VOL+": "Volume Up",
    "CH-": "Channel Down",
    "CH+": "Channel Up",
}
_ACRONYMS = {"AC", "AV", "EPG", "HDMI", "IR", "OK", "PC", "TV", "USB"}


def clean_text(value: str | None) -> str:
    """Remove device metadata bytes and normalize whitespace."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = _CONTROL_RE.sub(" ", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def decode_vendor_text(value: str | None) -> str:
    """Strictly decode a vendor base64 string, otherwise return clean raw text."""
    raw = clean_text(value)
    if not raw:
        return ""
    try:
        decoded_bytes = base64.b64decode(raw, validate=True)
        decoded = decoded_bytes.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return raw
    cleaned = clean_text(decoded)
    if not cleaned or sum(char.isprintable() for char in cleaned) / len(cleaned) < 0.9:
        return raw
    return cleaned


def slugify(value: str) -> str:
    """Return a stable, symbol-aware Home Assistant object-id stem."""
    value = clean_text(value).lower()
    value = value.replace("+", " plus ").replace("-", " minus ")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_") or "key"


def is_opaque_identifier(value: str | None) -> bool:
    """Return whether a value looks like a generated Tapo key identifier."""
    return bool(value and _OPAQUE_ID_RE.fullmatch(clean_text(value)))


def _title_case(value: str) -> str:
    words: list[str] = []
    for word in value.replace("_", " ").split():
        upper = word.upper()
        if upper in _ACRONYMS or word.isdigit():
            words.append(upper if upper in _ACRONYMS else word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def humanize_key_label(
    protocol_name: str | None,
    display_name: str | None,
    position: int,
) -> tuple[str, str]:
    """Return a readable label and the source used to derive it."""
    protocol = clean_text(protocol_name)
    decoded = decode_vendor_text(display_name)
    raw_had_controls = bool(display_name and _CONTROL_RE.search(str(display_name)))
    undecodable_base64 = bool(
        decoded
        and decoded == clean_text(display_name)
        and "=" in decoded
        and _BASE64_TOKEN_RE.fullmatch(decoded)
    )
    protocol_label = _KEY_ALIASES.get(protocol.upper())

    if protocol_label:
        return protocol_label, "protocol"

    if not protocol or is_opaque_identifier(protocol):
        if decoded and not is_opaque_identifier(decoded) and not raw_had_controls:
            return _title_case(decoded), "display_name"
        return f"Unlabeled Button {position}", "generated"

    # Control bytes and four-character vendor truncations are metadata, not labels.
    if (
        not decoded
        or raw_had_controls
        or undecodable_base64
        or is_opaque_identifier(decoded)
        or protocol.isdigit()
        or decoded.casefold().startswith(f"{protocol.casefold()} ")
        or (protocol.upper().startswith(decoded.upper()) and len(decoded) < len(protocol))
    ):
        return _title_case(protocol), "protocol"

    return _title_case(decoded), "display_name"


def humanize_remote_name(
    device_id: str,
    nickname: str | None,
    key_names: list[str],
    overrides: dict[str, str] | None = None,
) -> str:
    """Resolve a readable remote name while honoring an explicit override."""
    if override := clean_text((overrides or {}).get(device_id)):
        return override
    decoded = decode_vendor_text(nickname)
    if not decoded or decoded in key_names or is_opaque_identifier(decoded):
        return f"IR Remote {device_id[-4:]}"
    return _title_case(decoded) if decoded.isupper() else decoded
