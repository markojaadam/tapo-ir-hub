"""Minimal Mitsubishi Electric 144-bit A/C waveform helpers."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

MITSUBISHI_AC_STATE_LENGTH = 18
MITSUBISHI_AC_BITS = MITSUBISHI_AC_STATE_LENGTH * 8
MITSUBISHI_AC_SIGNATURE = bytes((0x23, 0xCB, 0x26, 0x01, 0x00))
MITSUBISHI_AC_FAN_HIGH = 3
MITSUBISHI_AC_FAN_REAL_MAX = 4


class MitsubishiAcPulseError(ValueError):
    """Raised when a learned waveform is not a usable Mitsubishi A/C frame."""


@dataclass(frozen=True)
class _DecodedFrame:
    state: bytes
    space_indices: tuple[int, ...]
    zero_space: int
    one_space: int


def _parse_pulse(pulse: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in pulse.split(",") if part.strip()]
    except ValueError as err:
        raise MitsubishiAcPulseError("Mitsubishi pulse must contain integers") from err
    if not values:
        raise MitsubishiAcPulseError("Mitsubishi pulse is empty")
    return values


def _valid_header(mark: int, space: int) -> bool:
    return 2500 <= mark <= 4500 and 1200 <= space <= 2200


def _decode_frame(values: list[int], start: int) -> _DecodedFrame | None:
    frame_end = start + 2 + MITSUBISHI_AC_BITS * 2 + 1
    if frame_end > len(values) or not _valid_header(values[start], values[start + 1]):
        return None

    bits: list[int] = []
    spaces: list[int] = []
    space_indices: list[int] = []
    for bit_index in range(MITSUBISHI_AC_BITS):
        mark_index = start + 2 + bit_index * 2
        space_index = mark_index + 1
        mark = values[mark_index]
        space = values[space_index]
        if not 250 <= mark <= 700:
            return None
        if 250 <= space <= 800:
            bit = 0
        elif 900 <= space <= 1800:
            bit = 1
        else:
            return None
        bits.append(bit)
        spaces.append(space)
        space_indices.append(space_index)

    footer_mark = values[start + 2 + MITSUBISHI_AC_BITS * 2]
    if not 250 <= footer_mark <= 700:
        return None

    state = bytearray(MITSUBISHI_AC_STATE_LENGTH)
    for bit_index, bit in enumerate(bits):
        if bit:
            state[bit_index // 8] |= 1 << (bit_index % 8)
    decoded = bytes(state)
    if decoded[:5] != MITSUBISHI_AC_SIGNATURE:
        return None
    if (sum(decoded[:-1]) & 0xFF) != decoded[-1]:
        return None

    zero_spaces = [space for bit, space in zip(bits, spaces) if bit == 0]
    one_spaces = [space for bit, space in zip(bits, spaces) if bit == 1]
    if not zero_spaces or not one_spaces:
        return None
    return _DecodedFrame(
        state=decoded,
        space_indices=tuple(space_indices),
        zero_space=round(median(zero_spaces)),
        one_space=round(median(one_spaces)),
    )


def decode_mitsubishi_ac_frames(pulse: str) -> list[bytes]:
    """Decode every valid Mitsubishi 144-bit frame found in a learned pulse."""
    values = _parse_pulse(pulse)
    frames: list[bytes] = []
    index = 0
    while index + 2 + MITSUBISHI_AC_BITS * 2 + 1 <= len(values):
        frame = _decode_frame(values, index)
        if frame is None:
            index += 1
            continue
        frames.append(frame.state)
        index = frame.space_indices[-1] + 2
    if not frames:
        raise MitsubishiAcPulseError("No valid Mitsubishi 144-bit A/C frame found")
    return frames


def promote_mitsubishi_ac_high_to_real_max(pulse: str) -> str:
    """Change fan=3 (high) to the hidden Mitsubishi fan=4 value.

    Only bit spaces that actually change are rewritten; all learned marks, gaps,
    and timing jitter remain untouched. Repeated frames must carry identical
    state and are updated together.
    """
    values = _parse_pulse(pulse)
    decoded_frames: list[_DecodedFrame] = []
    index = 0
    while index + 2 + MITSUBISHI_AC_BITS * 2 + 1 <= len(values):
        frame = _decode_frame(values, index)
        if frame is None:
            index += 1
            continue
        decoded_frames.append(frame)
        index = frame.space_indices[-1] + 2

    if not decoded_frames:
        raise MitsubishiAcPulseError("No valid Mitsubishi 144-bit A/C frame found")
    source = decoded_frames[0].state
    if any(frame.state != source for frame in decoded_frames[1:]):
        raise MitsubishiAcPulseError("Repeated Mitsubishi frames do not match")
    if (source[9] & 0b111) != MITSUBISHI_AC_FAN_HIGH:
        raise MitsubishiAcPulseError("Source Mitsubishi frame is not fan=3 (high)")

    target = bytearray(source)
    target[9] = (target[9] & ~0b111) | MITSUBISHI_AC_FAN_REAL_MAX
    target[-1] = sum(target[:-1]) & 0xFF

    for frame in decoded_frames:
        for bit_index, space_index in enumerate(frame.space_indices):
            old_bit = (source[bit_index // 8] >> (bit_index % 8)) & 1
            new_bit = (target[bit_index // 8] >> (bit_index % 8)) & 1
            if old_bit == new_bit:
                continue
            values[space_index] = frame.one_space if new_bit else frame.zero_space

    return ",".join(str(value) for value in values)
