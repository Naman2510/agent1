"""Wire format. Malformed frames must be rejected, never guessed at."""

from __future__ import annotations

import json

import pytest

from app.voice.audio import AudioFrame
from app.voice.protocol import (
    HEADER_BYTES,
    ProtocolError,
    ServerMessage,
    decode_audio,
    decode_control,
    encode_audio,
    encode_control,
)


def test_audio_frames_round_trip_with_their_fencing_token() -> None:
    frame = AudioFrame(turn_id=7, seq=1234, pcm=b"\x01\x02" * 320)
    decoded = decode_audio(encode_audio(frame))
    assert decoded == frame
    assert decoded.turn_id == 7
    assert decoded.seq == 1234


def test_large_turn_and_sequence_numbers_survive() -> None:
    """A long session must not wrap or truncate the fencing token."""
    frame = AudioFrame(turn_id=4_294_967_295, seq=4_294_967_295, pcm=b"\x00\x00")
    decoded = decode_audio(encode_audio(frame))
    assert decoded.turn_id == 4_294_967_295
    assert decoded.seq == 4_294_967_295


def test_frame_duration_is_derived_from_its_size() -> None:
    frame = AudioFrame(turn_id=0, seq=0, pcm=b"\x00" * 640)
    assert frame.duration_ms == 20


def test_a_frame_shorter_than_its_header_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="header"):
        decode_audio(b"\x00" * (HEADER_BYTES - 1))


def test_a_header_with_no_samples_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="no samples"):
        decode_audio(b"\x00" * HEADER_BYTES)


def test_an_odd_byte_count_is_rejected_rather_than_padded() -> None:
    """16-bit samples. Padding a truncated frame injects a click and shifts every timing."""
    with pytest.raises(ProtocolError, match="16-bit"):
        decode_audio(b"\x00" * HEADER_BYTES + b"\x01\x02\x03")


def test_control_frames_round_trip() -> None:
    raw = encode_control(ServerMessage.STATE, state="speaking", turn_id=3)
    assert json.loads(raw) == {"type": "state", "state": "speaking", "turn_id": 3}
    frame = decode_control(raw)
    assert frame.type == "state"
    assert frame.payload == {"state": "speaking", "turn_id": 3}


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="valid JSON"):
        decode_control("{not json")


def test_a_json_array_is_not_a_control_frame() -> None:
    with pytest.raises(ProtocolError, match="JSON object"):
        decode_control("[1, 2, 3]")


def test_a_frame_without_a_type_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="'type'"):
        decode_control('{"turn_id": 1}')
    with pytest.raises(ProtocolError, match="'type'"):
        decode_control('{"type": 42}')


def test_an_oversized_control_frame_is_rejected() -> None:
    """Control frames are small by design; a huge one is a bug or an allocation attempt."""
    with pytest.raises(ProtocolError, match="too large"):
        decode_control(json.dumps({"type": "user.text", "text": "x" * 20_000}))


def test_integer_fields_are_validated() -> None:
    frame = decode_control('{"type": "playback.ack", "played_ms": 250}')
    assert frame.get_int("played_ms") == 250

    bad = decode_control('{"type": "playback.ack", "played_ms": "250"}')
    with pytest.raises(ProtocolError, match="must be an integer"):
        bad.get_int("played_ms")

    # A bool is an int in Python, and accepting it here would be a silent type confusion.
    boolish = decode_control('{"type": "playback.ack", "played_ms": true}')
    with pytest.raises(ProtocolError, match="must be an integer"):
        boolish.get_int("played_ms")


def test_a_missing_integer_field_falls_back_to_its_default() -> None:
    frame = decode_control('{"type": "playback.ack"}')
    assert frame.get_int("played_ms", 0) == 0
