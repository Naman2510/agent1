"""WebSocket wire format (ARCHITECTURE §10).

Binary frames carry audio; text frames carry JSON control messages. Audio frames are prefixed
with `[turn_id:u32][seq:u32]` so both ends can drop frames belonging to a turn that has ended —
the fencing that closes the "ghost audio after cancel" class of bug, and makes the interruption
race testable rather than a matter of timing luck.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.voice.audio import AudioFrame

_HEADER = struct.Struct(">II")
HEADER_BYTES = _HEADER.size  # 8


class ClientMessage(StrEnum):
    SESSION_START = "session.start"
    PLAYBACK_ACK = "playback.ack"
    USER_INTERRUPT = "user.interrupt"
    USER_TEXT = "user.text"
    SESSION_REAUTH = "session.reauth"
    SESSION_END = "session.end"


class ServerMessage(StrEnum):
    READY = "ready"
    STT_PARTIAL = "stt.partial"
    STT_FINAL = "stt.final"
    STATE = "state"
    AGENT_ACTIVITY = "agent.activity"
    RAG_CITATIONS = "rag.citations"
    LLM_DELTA = "llm.delta"
    TTS_CANCEL = "tts.cancel"
    METRICS = "metrics"
    ERROR = "error"


class ProtocolError(ValueError):
    """A malformed frame. The connection is closed rather than guessed at."""


def encode_audio(frame: AudioFrame) -> bytes:
    return _HEADER.pack(frame.turn_id, frame.seq) + frame.pcm


def decode_audio(payload: bytes) -> AudioFrame:
    if len(payload) < HEADER_BYTES:
        raise ProtocolError(f"audio frame shorter than its {HEADER_BYTES}-byte header")
    turn_id, seq = _HEADER.unpack_from(payload, 0)
    pcm = payload[HEADER_BYTES:]
    if not pcm:
        raise ProtocolError("audio frame carries a header but no samples")
    if len(pcm) % 2:
        # 16-bit samples: an odd byte count means a truncated frame, and padding it would inject
        # a click and shift every subsequent timing.
        raise ProtocolError("audio payload is not a whole number of 16-bit samples")
    return AudioFrame(turn_id=turn_id, seq=seq, pcm=pcm)


def encode_control(message_type: ServerMessage | str, **payload: Any) -> str:
    """Serialise a control frame.

    The parameter is `message_type`, not `message`: several frames carry a `message` field of
    their own (errors, notably), and a collision here produced a TypeError only on the error
    path — i.e. exactly when something had already gone wrong.
    """
    return json.dumps({"type": str(message_type), **payload}, separators=(",", ":"))


@dataclass(frozen=True)
class ControlFrame:
    type: str
    payload: dict[str, Any]

    def get_int(self, key: str, default: int = 0) -> int:
        value = self.payload.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProtocolError(f"{key!r} must be an integer")
        return value


def decode_control(raw: str) -> ControlFrame:
    if len(raw) > 16_384:
        # Control frames are small by design; an oversized one is either a bug or an attempt to
        # make the server allocate.
        raise ProtocolError("control frame too large")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"control frame is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("control frame must be a JSON object")
    message_type = data.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("control frame is missing a string 'type'")
    return ControlFrame(type=message_type, payload={k: v for k, v in data.items() if k != "type"})
