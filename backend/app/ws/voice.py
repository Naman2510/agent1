"""The voice WebSocket endpoint.

Authentication happens at the handshake, via the `Sec-WebSocket-Protocol` header, because the
browser WebSocket API cannot set `Authorization` and a token in the query string lands in access
logs (ARCHITECTURE §10). The client offers `["bearer", "<token>"]`; the server selects `bearer`.

The connection is capped at 60 minutes and accepts a `session.reauth` frame so a long tutoring
conversation can outlive a 15-minute access token without the token itself living longer (Gate 0
finding M-08).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import LimitClass, RateLimiter
from app.core.security import decode_access_token
from app.db.repositories.sessions import MessageRepository, SessionRepository
from app.db.repositories.users import StudentRepository, UserRepository
from app.providers.registry import build_stt, build_tts
from app.services.conversation import ConversationService
from app.services.usage import UsageLedger
from app.voice.audio import FRAME_BYTES, AudioFrame
from app.voice.protocol import (
    ClientMessage,
    ProtocolError,
    ServerMessage,
    decode_audio,
    decode_control,
    encode_control,
)
from app.voice.session import VoiceSession, VoiceSessionConfig
from app.voice.vad import VadGate, VadSettings, VoiceDetector

router = APIRouter()
log = structlog.get_logger(__name__)

MAX_CONNECTION_SECONDS = 3600
BEARER_SUBPROTOCOL = "bearer"
# Frames are 20 ms of 16 kHz mono PCM plus an 8-byte header. Anything much larger is a bug or an
# attempt to make the server allocate.
MAX_AUDIO_MESSAGE_BYTES = FRAME_BYTES * 4 + 64


class _WebSocketTransport:
    """Adapts a FastAPI WebSocket to the session's `Transport` protocol."""

    def __init__(self, socket: WebSocket) -> None:
        self._socket = socket

    async def send_control(self, message_type: ServerMessage | str, **payload: Any) -> None:
        await self._socket.send_text(encode_control(message_type, **payload))

    async def send_audio(self, turn_id: int, seq: int, pcm: bytes) -> None:
        from app.voice.protocol import encode_audio

        await self._socket.send_bytes(encode_audio(AudioFrame(turn_id=turn_id, seq=seq, pcm=pcm)))


def _token_from_subprotocols(socket: WebSocket) -> str | None:
    raw = socket.headers.get("sec-websocket-protocol", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2 and parts[0] == BEARER_SUBPROTOCOL:
        return parts[1]
    return None


def _build_detector(settings: Settings) -> VoiceDetector:
    """Silero in production; the scripted detector only where explicitly configured.

    A missing model file is a hard failure rather than a silent downgrade to something that
    cannot tell speech from a fan.
    """
    if settings.vad_provider == "scripted":  # pragma: no cover - test/demo configuration only
        from app.voice.vad import ScriptedVoiceDetector

        return ScriptedVoiceDetector([])
    from app.voice.vad import SileroVoiceDetector

    return SileroVoiceDetector(settings.silero_vad_path)


@router.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket, session_id: uuid.UUID) -> None:
    app = websocket.app
    settings: Settings = app.state.settings

    token = _token_from_subprotocols(websocket)
    if not token:
        # Rejected before accept, so no application state is created for an unauthenticated peer.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="missing credentials")
        return

    factory: async_sessionmaker = app.state.session_factory
    try:
        payload = decode_access_token(settings, token)
        user_id = uuid.UUID(payload["sub"])
    except (AppError, KeyError, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid credentials")
        return

    limiter: RateLimiter = app.state.rate_limiter
    if not (await limiter.check(LimitClass.AI, str(user_id))).allowed:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="rate limited")
        return

    async with factory() as db:
        user = await UserRepository(db).get_by_id(user_id)
        student = await StudentRepository(db).get_by_user_id(user_id) if user else None
        if user is None or not user.is_active or student is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="account unavailable"
            )
            return

        conversation_session = await SessionRepository(db).get_for_student(session_id, student.id)
        if conversation_session is None:
            # Indistinguishable from "not yours", as on the HTTP surface.
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unknown session")
            return

        ledger = UsageLedger(app.state.redis, settings)
        try:
            await ledger.check_voice_quota(str(student.id))
        except AppError as exc:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=exc.code)
            return

        await websocket.accept(subprotocol=BEARER_SUBPROTOCOL)

        voice = VoiceSession(
            student_id=student.id,
            session_id=session_id,
            transport=_WebSocketTransport(websocket),
            vad=VadGate(
                _build_detector(settings),
                VadSettings(
                    enter_threshold=settings.vad_enter_threshold,
                    exit_threshold=settings.vad_exit_threshold,
                    min_speech_ms=settings.vad_min_speech_ms,
                    min_silence_ms=settings.vad_min_silence_ms,
                ),
            ),
            stt=build_stt(settings),
            tts=build_tts(settings),
            conversation=ConversationService(
                llm=app.state.llm,
                messages=MessageRepository(db),
                ledger=ledger,
                settings=settings,
            ),
            settings=settings,
            config=VoiceSessionConfig(pre_roll_ms=settings.voice_pre_roll_ms),
        )

        started = time.monotonic()
        audio_ms = 0
        await voice.start()

        try:
            while True:
                if time.monotonic() - started > MAX_CONNECTION_SECONDS:
                    await websocket.close(
                        code=status.WS_1000_NORMAL_CLOSURE, reason="connection age limit"
                    )
                    break

                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break

                if (payload_bytes := message.get("bytes")) is not None:
                    if len(payload_bytes) > MAX_AUDIO_MESSAGE_BYTES:
                        await _fail(websocket, "frame_too_large", "Audio frame too large.")
                        continue
                    try:
                        frame = decode_audio(payload_bytes)
                    except ProtocolError as exc:
                        await _fail(websocket, "bad_frame", str(exc))
                        continue
                    audio_ms += frame.duration_ms
                    await voice.handle_audio(frame)
                    continue

                if (payload_text := message.get("text")) is not None:
                    try:
                        control = decode_control(payload_text)
                    except ProtocolError as exc:
                        await _fail(websocket, "bad_control", str(exc))
                        continue
                    if control.type == ClientMessage.SESSION_END:
                        break
                    await _dispatch_control(voice, control, settings=settings, socket=websocket)

        except WebSocketDisconnect:
            pass
        finally:
            await voice.close()
            # Metered as audio is consumed, so an abandoned session still counts what it used.
            await ledger.record_voice_seconds(str(student.id), audio_ms // 1000)
            await db.commit()
            log.info(
                "voice.session_closed",
                session_id=str(session_id),
                audio_seconds=audio_ms // 1000,
                dropped_frames=voice.dropped_frames,
            )


async def _dispatch_control(
    voice: VoiceSession, control: Any, *, settings: Settings, socket: WebSocket
) -> None:
    if control.type == ClientMessage.PLAYBACK_ACK:
        await voice.handle_playback_ack(
            turn_id=control.get_int("turn_id"), played_ms=control.get_int("played_ms")
        )
    elif control.type == ClientMessage.USER_INTERRUPT:
        await voice.handle_user_interrupt(turn_id=control.get_int("turn_id"))
    elif control.type == ClientMessage.USER_TEXT:
        text = str(control.payload.get("text", ""))[:2000].strip()
        if text:
            await voice.handle_text(text=text)
    elif control.type == ClientMessage.SESSION_REAUTH:
        token = str(control.payload.get("access_token", ""))
        try:
            decode_access_token(settings, token)
        except AppError:
            await _fail(socket, "reauth_failed", "Token rejected.")
    elif control.type == ClientMessage.SESSION_START:
        pass  # already started at accept
    else:
        await _fail(socket, "unknown_control", f"Unsupported control frame {control.type!r}.")


async def _fail(socket: WebSocket, code: str, message: str) -> None:
    await socket.send_text(encode_control(ServerMessage.ERROR, code=code, message=message))
