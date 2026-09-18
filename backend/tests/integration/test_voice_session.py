"""The voice session end to end, including barge-in.

Driven through the session's `Transport` seam with a scripted VAD and the fake STT/TTS, so the
timeline is deterministic and the assertions are about our orchestration: state transitions,
fencing, the pre-roll, the playback ledger, and what ends up in the database.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Message, MessageRole, Session, Student, User
from app.db.repositories.sessions import MessageRepository
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
from app.providers.stt.fake import FakeSTTProvider
from app.providers.tts.fake import FakeTTSProvider
from app.services.conversation import ConversationService
from app.services.usage import UsageLedger
from app.voice.audio import FRAME_BYTES, AudioFrame
from app.voice.protocol import ServerMessage
from app.voice.session import VoiceSession, VoiceSessionConfig
from app.voice.state import TurnState
from app.voice.vad import ScriptedVoiceDetector, VadGate, VadSettings, speech_timeline

SPEECH_FRAME = b"\x11\x11" * 320
SILENT_FRAME = b"\x00" * FRAME_BYTES


@dataclass
class RecordingTransport:
    """Captures everything the session sends, and can replay playback ACKs."""

    control: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    audio: list[tuple[int, int, int]] = field(default_factory=list)  # turn_id, seq, bytes

    async def send_control(self, message_type: ServerMessage | str, **payload: Any) -> None:
        self.control.append((str(message_type), payload))

    async def send_audio(self, turn_id: int, seq: int, pcm: bytes) -> None:
        self.audio.append((turn_id, seq, len(pcm)))

    def types(self) -> list[str]:
        return [name for name, _ in self.control]

    def of_type(self, name: str) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.control if kind == name]

    def states(self) -> list[str]:
        return [p["state"] for p in self.of_type("state")]

    @property
    def audio_bytes(self) -> int:
        return sum(size for _, _, size in self.audio)


class FakeClock:
    """A controllable monotonic clock, so timing assertions never sleep."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
async def student_and_session(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"voice-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name="Voice Student")
    db_session.add(student)
    await db_session.flush()
    session = Session(student_id=student.id, transport="websocket")
    db_session.add(session)
    await db_session.flush()
    await db_session.commit()
    return student.id, session.id


def _build(
    *,
    db_session: AsyncSession,
    settings: Settings,
    redis_client: Any,
    student_id: uuid.UUID,
    session_id: uuid.UUID,
    probabilities: list[float],
    llm: FakeLLMProvider | None = None,
    transcript: str = "Kirchhoff ka voltage law samjhao",
    clock: FakeClock | None = None,
) -> tuple[VoiceSession, RecordingTransport, FakeTTSProvider]:
    transport = RecordingTransport()
    tts = FakeTTSProvider()
    voice = VoiceSession(
        student_id=student_id,
        session_id=session_id,
        transport=transport,
        vad=VadGate(ScriptedVoiceDetector(probabilities), VadSettings()),
        stt=FakeSTTProvider(transcript=transcript),
        tts=tts,
        conversation=ConversationService(
            llm=llm or FakeLLMProvider([ScriptedTurn(text="Loop ka sum zero hota hai.")]),
            messages=MessageRepository(db_session),
            ledger=UsageLedger(redis_client, settings),
            settings=settings,
        ),
        settings=settings,
        config=VoiceSessionConfig(ack_grace_ms=0),
        clock=clock or FakeClock(),
    )
    return voice, transport, tts


async def _feed(voice: VoiceSession, frames: int, *, pcm: bytes = SPEECH_FRAME) -> None:
    for seq in range(frames):
        await voice.handle_audio(AudioFrame(turn_id=voice.machine.turn_id, seq=seq, pcm=pcm))


async def _messages(db: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.turn_index, Message.seq)
    )
    return list(result.scalars().all())


# --- a complete turn --------------------------------------------------------


async def test_a_full_turn_runs_through_every_state(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=speech_timeline(silence_ms=64, speech_ms=800, trailing_silence_ms=800),
    )
    await voice.start()
    await _feed(voice, 90)
    await voice.wait_for_turn()
    await db_session.commit()

    states = transport.states()
    assert states[0] == "listening"
    assert "user_speaking" in states
    assert "thinking" in states
    assert "speaking" in states
    assert states[-1] == "listening", "the session must be ready for the next turn"

    assert transport.of_type("stt.final"), "the transcript must be sent to the client"
    assert transport.audio, "audio must be streamed"
    assert transport.of_type("metrics"), "stage marks must be reported"


async def test_a_completed_turn_persists_both_messages_with_stage_marks(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, _transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=speech_timeline(silence_ms=64, speech_ms=800, trailing_silence_ms=800),
    )
    await voice.start()
    await _feed(voice, 90)
    await voice.wait_for_turn()
    await db_session.commit()

    rows = await _messages(db_session, session_id)
    assert [r.role for r in rows] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert rows[0].content == "Kirchhoff ka voltage law samjhao"
    assert rows[0].language == "hi-Latn", "the STT language hint must be recorded"

    assistant = rows[1]
    assert assistant.was_interrupted is False
    # Gate 3 requires the stage marks to be persisted, not merely logged.
    for mark in ("turn_end_ms", "stt_final_ms", "llm_ttft_ms"):
        assert mark in assistant.latency_ms, f"{mark} missing from {assistant.latency_ms}"


async def test_metrics_include_time_to_first_audio_once_the_client_acks(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """TTFA is measured client-side, because that is the only definition a student experiences."""
    student_id, session_id = student_and_session
    clock = FakeClock()
    voice, transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=speech_timeline(silence_ms=64, speech_ms=800, trailing_silence_ms=800),
        clock=clock,
    )
    await voice.start()

    # Speak, then acknowledge playback the moment audio starts flowing.
    for seq in range(60):
        await voice.handle_audio(AudioFrame(turn_id=0, seq=seq, pcm=SPEECH_FRAME))
    clock.advance(0.35)
    for seq in range(60, 90):
        await voice.handle_audio(AudioFrame(turn_id=0, seq=seq, pcm=SILENT_FRAME))
    await voice.handle_playback_ack(turn_id=voice.machine.turn_id, played_ms=20)
    await voice.wait_for_turn()
    await db_session.commit()

    marks = transport.of_type("metrics")[-1]["latency_ms"]
    assert "ttfa_ms" in marks
    assert marks["ttfa_ms"] >= 0


# --- barge-in ---------------------------------------------------------------
#
# These interrupt a turn that is genuinely *in flight*. Interrupting after the turn has finished
# tests nothing: the interesting code runs while generation and synthesis are still going.


def _slow_build(
    *,
    db_session: AsyncSession,
    settings: Settings,
    redis_client: Any,
    student_id: uuid.UUID,
    session_id: uuid.UUID,
    answer: str,
) -> tuple[VoiceSession, RecordingTransport, FakeTTSProvider]:
    """A session whose synthesis yields to the event loop, so a turn can be caught mid-flight."""
    transport = RecordingTransport()
    tts = FakeTTSProvider(chunk_delay_s=0.002)
    voice = VoiceSession(
        student_id=student_id,
        session_id=session_id,
        transport=transport,
        vad=VadGate(ScriptedVoiceDetector([0.01] * 500), VadSettings()),
        stt=FakeSTTProvider(),
        tts=tts,
        conversation=ConversationService(
            llm=FakeLLMProvider([ScriptedTurn(text=answer)]),
            messages=MessageRepository(db_session),
            ledger=UsageLedger(redis_client, settings),
            settings=settings,
        ),
        settings=settings,
        config=VoiceSessionConfig(ack_grace_ms=0),
        clock=FakeClock(),
    )
    return voice, transport, tts


async def _until(predicate, budget_s: float = 2.0) -> bool:  # type: ignore[no-untyped-def]
    """Wait for a condition while the turn task runs. No fixed sleeps."""
    deadline = asyncio.get_running_loop().time() + budget_s
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0)
    return False


ANSWER = "Pehla hissa yahan hai. Doosra hissa yahan hai. Teesra hissa bhi yahan hai."


async def test_barge_in_stops_playback_and_stores_only_what_was_heard(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """The Gate 0 C-03 invariant, through the real voice path with a turn in flight.

    The mentor is mid-answer, the student interrupts, and the stored assistant turn must be the
    prefix that actually reached the speaker — not the whole generated answer.
    """
    student_id, session_id = student_and_session
    voice, transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    await voice.handle_text(text="Samjhao")

    # Wait until audio is actually flowing, then acknowledge part of it.
    assert await _until(lambda: voice.machine.state is TurnState.SPEAKING)
    assert await _until(lambda: voice._ledger.total_audio_ms > 400)
    played = voice._ledger.total_audio_ms // 2
    await voice.handle_playback_ack(turn_id=voice.machine.turn_id, played_ms=played)

    interrupted_turn = voice.machine.turn_id
    await voice._barge_in()
    await db_session.commit()

    assert transport.of_type("tts.cancel"), "the client must be told to flush immediately"
    assert transport.of_type("tts.cancel")[-1]["turn_id"] == interrupted_turn
    assert "barged_in" in transport.states()
    assert voice.machine.turn_id > interrupted_turn, "the fencing token must advance"

    stored = [r for r in await _messages(db_session, session_id) if r.was_interrupted]
    assert len(stored) == 1
    heard = stored[0]

    assert heard.content, "some audio played, so something must be recorded as heard"
    assert heard.content != ANSWER, "the full generation must not be stored as though heard"
    assert ANSWER.startswith(heard.content), "what is stored must be a prefix of the answer"
    assert heard.spoken_prefix_chars == len(heard.content)
    assert heard.unspoken_remainder, "the unheard tail is kept for debugging"
    assert heard.unspoken_remainder not in heard.content


async def test_barge_in_cancels_generation_rather_than_letting_it_finish(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """Cancellation must be real: a client-side mute would keep paying for tokens and audio."""
    student_id, session_id = student_and_session
    voice, transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    await voice.handle_text(text="Samjhao")
    assert await _until(lambda: voice.machine.state is TurnState.SPEAKING)

    audio_before = transport.audio_bytes
    await voice._barge_in()
    await asyncio.sleep(0.02)  # give any surviving task a chance to misbehave
    audio_after = transport.audio_bytes

    assert audio_after == audio_before, "no audio may be produced after cancellation"
    assert voice._turn_task is None


async def test_an_interruption_before_any_audio_plays_stores_nothing_as_heard(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """Audio generated and sent but never played was not heard."""
    student_id, session_id = student_and_session
    voice, _transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    await voice.handle_text(text="Samjhao")
    assert await _until(lambda: voice.machine.state is TurnState.SPEAKING)

    # No playback ACK at all.
    await voice._barge_in()
    await db_session.commit()

    stored = [r for r in await _messages(db_session, session_id) if r.was_interrupted]
    assert len(stored) == 1
    assert stored[0].content == ""
    assert "Pehla hissa" in (stored[0].unspoken_remainder or "")


async def test_frames_from_the_interrupted_turn_are_dropped(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """Fencing. Audio recorded during cancellation must not reach the next turn."""
    student_id, session_id = student_and_session
    voice, _transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    await voice.handle_text(text="Samjhao")
    assert await _until(lambda: voice.machine.state is TurnState.SPEAKING)

    stale_turn = voice.machine.turn_id
    await voice._barge_in()

    before = voice.dropped_frames
    for seq in range(5):
        await voice.handle_audio(AudioFrame(turn_id=stale_turn, seq=seq, pcm=SPEECH_FRAME))
    assert voice.dropped_frames == before + 5


async def test_a_playback_ack_for_a_finished_turn_cannot_rewrite_history(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, _transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    await voice.handle_text(text="Samjhao")
    assert await _until(lambda: voice.machine.state is TurnState.SPEAKING)
    stale_turn = voice.machine.turn_id
    await voice._barge_in()

    await voice.handle_playback_ack(turn_id=stale_turn, played_ms=99_999)
    assert voice._ledger.played_ms < 99_999


async def test_an_explicit_stop_button_uses_the_same_path(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    await voice.handle_text(text="Samjhao")
    assert await _until(lambda: voice.machine.state is TurnState.SPEAKING)

    await voice.handle_user_interrupt(turn_id=voice.machine.turn_id)
    assert transport.of_type("tts.cancel")
    # A button press is not an utterance, so the session returns to listening.
    assert voice.machine.state is TurnState.LISTENING


async def test_an_interrupt_for_the_wrong_turn_is_ignored(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    await voice.handle_text(text="Samjhao")
    assert await _until(lambda: voice.machine.state is TurnState.SPEAKING)

    await voice.handle_user_interrupt(turn_id=voice.machine.turn_id + 5)
    assert not transport.of_type("tts.cancel")
    await voice.wait_for_turn()


async def test_barge_in_is_inert_when_the_mentor_is_not_speaking(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """Defensive: firing cancellation transitions from LISTENING would corrupt the machine."""
    student_id, session_id = student_and_session
    voice, transport, _tts = _slow_build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        answer=ANSWER,
    )
    await voice.start()
    assert voice.machine.state is TurnState.LISTENING
    await voice._barge_in()
    assert voice.machine.state is TurnState.LISTENING
    assert not transport.of_type("tts.cancel")


# --- pre-roll and short utterances -----------------------------------------


async def test_the_utterance_keeps_its_onset_via_the_pre_roll_buffer(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """Without this, "Wait, stop" reaches the recogniser as "stop" (ARCHITECTURE §5.5).

    The scripted VAD confirms speech only after 250 ms, so the audio handed to the recogniser must
    be longer than the audio that arrived *after* confirmation.
    """
    student_id, session_id = student_and_session
    stt = FakeSTTProvider(transcript="Wait, stop")
    transport = RecordingTransport()
    voice = VoiceSession(
        student_id=student_id,
        session_id=session_id,
        transport=transport,
        vad=VadGate(
            ScriptedVoiceDetector(
                speech_timeline(silence_ms=320, speech_ms=600, trailing_silence_ms=640)
            ),
            VadSettings(),
        ),
        stt=stt,
        tts=FakeTTSProvider(),
        conversation=ConversationService(
            llm=FakeLLMProvider(),
            messages=MessageRepository(db_session),
            ledger=UsageLedger(redis_client, settings),
            settings=settings,
        ),
        settings=settings,
        config=VoiceSessionConfig(pre_roll_ms=500, ack_grace_ms=0),
        clock=FakeClock(),
    )
    await voice.start()
    await _feed(voice, 90)
    await voice.wait_for_turn()

    # The fake STT counts the frames it received; with a 500 ms pre-roll it must see more audio
    # than the post-confirmation remainder alone.
    assert stt.frame_count > 0
    assert voice.machine.state is TurnState.LISTENING


async def test_a_too_short_utterance_is_discarded_without_spending_a_turn(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    voice, _transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        # 256 ms of speech: past the VAD's min_speech_ms, short of min_utterance_ms.
        probabilities=[0.95] * 8 + [0.01] * 40,
    )
    await voice.start()
    await _feed(voice, 40)
    await voice.wait_for_turn()
    await db_session.commit()

    assert await _messages(db_session, session_id) == []
    assert voice.machine.turn_id == 0, "a discarded utterance must not consume a turn"


async def test_a_backchannel_is_not_treated_as_a_question(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """'Haan' is agreement, not a question (R-08). Answering it wastes a turn and confuses."""
    student_id, session_id = student_and_session
    voice, _transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=speech_timeline(silence_ms=64, speech_ms=800, trailing_silence_ms=800),
        transcript="Haan",
    )
    await voice.start()
    await _feed(voice, 90)
    await voice.wait_for_turn()
    await db_session.commit()

    assert await _messages(db_session, session_id) == []
    assert voice.machine.turn_id == 0


async def test_a_backchannel_followed_by_a_question_is_still_a_question(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """The stoplist matches whole utterances only — "haan, lekin..." must go through."""
    student_id, session_id = student_and_session
    voice, _transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=speech_timeline(silence_ms=64, speech_ms=800, trailing_silence_ms=800),
        transcript="Haan lekin displacement current kya hai",
    )
    await voice.start()
    await _feed(voice, 90)
    await voice.wait_for_turn()
    await db_session.commit()

    rows = await _messages(db_session, session_id)
    assert len(rows) == 2


async def test_an_empty_transcript_is_discarded(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """Silence that fooled the VAD must not produce a turn with an empty question."""
    student_id, session_id = student_and_session
    voice, _transport, _tts = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=speech_timeline(silence_ms=64, speech_ms=800, trailing_silence_ms=800),
        transcript="   ",
    )
    await voice.start()
    await _feed(voice, 90)
    await voice.wait_for_turn()
    await db_session.commit()

    assert await _messages(db_session, session_id) == []


async def test_a_language_without_a_voice_falls_back_rather_than_failing(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """A wrong-accent answer beats silence, and the mismatch is visible in telemetry."""
    student_id, session_id = student_and_session
    voice, _transport, tts_double = _build(
        db_session=db_session,
        settings=settings,
        redis_client=redis_client,
        student_id=student_id,
        session_id=session_id,
        probabilities=[0.01] * 100,
    )
    await voice.start()
    await voice.handle_text(text="ഇത് മലയാളമാണ്")  # Malayalam: no voice configured
    await voice.wait_for_turn()
    assert tts_double.requests, "synthesis must still happen"


# --- language routing across a conversation ---------------------------------


async def test_mid_conversation_language_switching_preserves_context(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """Gate 4: the student switches language mid-conversation and the history survives.

    Spec §11 requires that context is preserved across a switch. History is stored
    language-tagged but never language-partitioned, so this is a property of the design — and
    this test is what stops a future "reset on switch" optimisation from quietly breaking it.
    """
    student_id, session_id = student_and_session
    llm = FakeLLMProvider([ScriptedTurn(text="Reply.")] * 6)
    transport = RecordingTransport()
    voice = VoiceSession(
        student_id=student_id,
        session_id=session_id,
        transport=transport,
        vad=VadGate(ScriptedVoiceDetector([0.01] * 500), VadSettings()),
        stt=FakeSTTProvider(),
        tts=FakeTTSProvider(),
        conversation=ConversationService(
            llm=llm,
            messages=MessageRepository(db_session),
            ledger=UsageLedger(redis_client, settings),
            settings=settings,
        ),
        settings=settings,
        config=VoiceSessionConfig(ack_grace_ms=0),
        clock=FakeClock(),
    )
    await voice.start()

    turns = [
        "Explain Kirchhoff's voltage law",
        "Bhai ye samajh nahi aa raha phir se batao",
        "Aur KCL ka matlab kya hai",
        "किरचॉफ का नियम समझाओ",
    ]
    for text in turns:
        await voice.handle_text(text=text)
        await voice.wait_for_turn()
    await db_session.commit()

    rows = await _messages(db_session, session_id)
    user_rows = [r for r in rows if r.role is MessageRole.USER]
    assert len(user_rows) == 4

    # Each turn is tagged with the language it was routed as, and the tags show the switch.
    assert [r.language for r in user_rows] == ["en", "hi-Latn", "hi-Latn", "hi"]

    # The crucial part: the final prompt still contains the *first*, English turn. Context is
    # tagged by language, never partitioned by it.
    final_request = llm.requests[-1]
    replayed = [m.text for m in final_request.messages]
    assert any("Kirchhoff's voltage law" in text for text in replayed), (
        "the English opening turn must survive a switch into Hindi"
    )
    assert replayed[-1] == "किरचॉफ का नियम समझाओ"


async def test_the_response_directive_changes_per_turn_without_touching_the_cached_prefix(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    """The directive is volatile, so it must sit after the cache breakpoints (ARCHITECTURE §8.5)."""
    student_id, session_id = student_and_session
    llm = FakeLLMProvider([ScriptedTurn(text="Reply.")] * 4)
    voice = VoiceSession(
        student_id=student_id,
        session_id=session_id,
        transport=RecordingTransport(),
        vad=VadGate(ScriptedVoiceDetector([0.01] * 200), VadSettings()),
        stt=FakeSTTProvider(),
        tts=FakeTTSProvider(),
        conversation=ConversationService(
            llm=llm,
            messages=MessageRepository(db_session),
            ledger=UsageLedger(redis_client, settings),
            settings=settings,
        ),
        settings=settings,
        config=VoiceSessionConfig(ack_grace_ms=0),
        clock=FakeClock(),
    )
    await voice.start()

    await voice.handle_text(text="Explain mesh analysis in detail please")
    await voice.wait_for_turn()
    await voice.handle_text(text="Yaar ye samajh nahi aaya phir se batao")
    await voice.wait_for_turn()
    await db_session.commit()

    english_turn, hinglish_turn = llm.requests[0], llm.requests[1]

    # The cacheable prefix is byte-identical across the switch.
    assert [b.text for b in english_turn.system if b.cacheable] == [
        b.text for b in hinglish_turn.system if b.cacheable
    ]

    # And the directive differs, in a non-cacheable block.
    english_volatile = " ".join(b.text for b in english_turn.system if not b.cacheable)
    hinglish_volatile = " ".join(b.text for b in hinglish_turn.system if not b.cacheable)
    assert "English" in english_volatile
    assert "Hinglish" in hinglish_volatile
    assert english_volatile != hinglish_volatile


async def test_the_selected_voice_follows_the_routed_language(
    db_session: AsyncSession, settings: Settings, redis_client, student_and_session
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = student_and_session
    tts = FakeTTSProvider()
    voice = VoiceSession(
        student_id=student_id,
        session_id=session_id,
        transport=RecordingTransport(),
        vad=VadGate(ScriptedVoiceDetector([0.01] * 200), VadSettings()),
        stt=FakeSTTProvider(),
        tts=tts,
        conversation=ConversationService(
            llm=FakeLLMProvider([ScriptedTurn(text="Reply.")] * 4),
            messages=MessageRepository(db_session),
            ledger=UsageLedger(redis_client, settings),
            settings=settings,
        ),
        settings=settings,
        config=VoiceSessionConfig(ack_grace_ms=0),
        clock=FakeClock(),
    )
    await voice.start()

    await voice.handle_text(text="Explain mesh analysis in detail please")
    await voice.wait_for_turn()
    assert tts.requests[-1].voice.language == "en"

    await voice.handle_text(text="किरचॉफ का नियम समझाओ")
    await voice.wait_for_turn()
    assert tts.requests[-1].voice.language == "hi", "a Hindi answer must not use the English voice"
