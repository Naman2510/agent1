"""The voice session: one WebSocket, one student, many turns.

This is where the Phase 0 design either holds together or does not. It owns the state machine,
the fencing token, the pre-roll buffer, the playback ledger, and cancellation — and it is written
against a `Transport` protocol rather than a WebSocket so all of that is testable without a
network.

The cancellation path is the part worth reading. On confirmed speech while the mentor is talking:

1. tell the client to flush its audio queue *first* — audible silence is what the student
   experiences as "it stopped", and everything else can take its time;
2. cancel synthesis and generation;
3. wait briefly for a final playback ACK, then resolve the ledger into the text actually heard;
4. persist that prefix, bump the fencing token, and let the interrupting utterance continue into
   the next turn.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from app.agent.language import script_of
from app.core.config import Settings
from app.providers.stt.base import (
    FinalTranscript,
    PartialTranscript,
    STTProvider,
    TranscriptionContext,
)
from app.providers.tts.base import SynthesisRequest, TTSProvider, Voice
from app.services.conversation import ConversationService
from app.voice import marks as stage
from app.voice.audio import (
    FRAME_MS,
    AudioFrame,
    PreRollBuffer,
    WindowAssembler,
    bytes_to_ms,
)
from app.voice.chunker import SentenceChunker
from app.voice.marks import TurnMarks
from app.voice.playback import PlaybackLedger
from app.voice.protocol import ServerMessage
from app.voice.state import IllegalTransitionError, Trigger, TurnState, TurnStateMachine
from app.voice.turn_detector import TurnDetector
from app.voice.vad import VadEvent, VadGate

log = structlog.get_logger(__name__)


class Transport(Protocol):
    """What the session needs from a connection. A WebSocket satisfies it; so does a test double."""

    async def send_control(self, message_type: ServerMessage | str, **payload: Any) -> None: ...

    async def send_audio(self, turn_id: int, seq: int, pcm: bytes) -> None: ...


@dataclass
class _LedgerDelivery:
    """Adapts the playback ledger to the conversation service's delivery seam.

    `remainder` is composed from the ledger plus any text that was generated but never
    synthesised, because those are two different kinds of "unheard" and both belong in the
    debugging record.
    """

    ledger: PlaybackLedger
    pending_text: Callable[[], str]

    def delivered(self) -> str:
        return self.ledger.spoken_prefix()

    def remainder(self) -> str:
        # Note: the ledger works in chunked text, which the chunker has stripped, so this is the
        # answer *as spoken* rather than byte-identical to the raw generation.
        return self.ledger.unspoken_remainder() + self.pending_text()


# Short acknowledgements are agreement, not interruption, and not questions (R-08). Matched
# against the whole transcript, case-folded, so "Hmm." and "haan" are both caught.
BACKCHANNELS = frozenset(
    {
        "hmm",
        "hm",
        "mhm",
        "mm",
        "uh huh",
        "uh-huh",
        "ok",
        "okay",
        "yeah",
        "yes",
        "right",
        "haan",
        "haa",
        "ha",
        "achha",
        "acha",
        "theek",
        "thik",
        "thik hai",
        "sahi",
        "aama",
        "aamaa",
        "sari",
        "seri",
    }
)


@dataclass
class VoiceSessionConfig:
    pre_roll_ms: int = 500
    # Long enough to be a *question*, not merely long enough to be speech. The VAD already
    # refuses anything below min_speech_ms, so without a second, higher threshold a 300 ms
    # "hmm" becomes a turn — complete with an LLM call and a bill.
    min_utterance_ms: int = 400
    # A pause shorter than this, with nothing yet played, is a continued thought rather than an
    # interruption (ARCHITECTURE §5.6).
    merge_window_ms: int = 1200
    # How long to wait for the client's final playback ACK before resolving the ledger. Short:
    # the student is already talking, and a stale prefix is better than a stalled session.
    ack_grace_ms: int = 150
    max_utterance_ms: int = 30_000
    tts_sample_rate: int = 24_000


@dataclass
class VoiceSession:
    student_id: uuid.UUID
    session_id: uuid.UUID
    transport: Transport
    vad: VadGate
    stt: STTProvider
    tts: TTSProvider
    conversation: ConversationService
    settings: Settings
    config: VoiceSessionConfig = field(default_factory=VoiceSessionConfig)
    clock: Callable[[], float] = time.perf_counter

    def __post_init__(self) -> None:
        self.machine = TurnStateMachine()
        self._windows = WindowAssembler()
        self._preroll = PreRollBuffer(self.config.pre_roll_ms)
        self._utterance = bytearray()
        self._capturing = False
        self._turn_task: asyncio.Task[None] | None = None
        self._ledger = PlaybackLedger()
        self._marks = TurnMarks(clock=self.clock)
        self._chunker = SentenceChunker()
        self._detector = TurnDetector(min_silence_ms=self.vad.settings.min_silence_ms)
        self._audio_seq = 0
        self._committed_at: float | None = None
        self._speech_ms = 0
        self._pending_merge_text: str = ""
        self._voice = self._select_voice("en")
        self.dropped_frames = 0

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self.machine.fire(Trigger.SESSION_START)
        await self._announce_state()
        await self.transport.send_control(
            ServerMessage.READY,
            sample_rate=self.stt.audio_format.sample_rate,
            frame_ms=FRAME_MS,
            tts_sample_rate=self.config.tts_sample_rate,
        )

    async def close(self) -> None:
        await self._cancel_turn_task()
        if self.machine.can(Trigger.SESSION_END):
            self.machine.fire(Trigger.SESSION_END)

    # --- inbound audio -----------------------------------------------------

    async def handle_audio(self, frame: AudioFrame) -> None:
        """Feed one 20 ms frame through VAD and turn detection.

        Frames from a turn that has already ended are dropped: audio recorded during cancellation
        must not be attributed to the next turn.
        """
        if not self.machine.accepts_frame(frame.turn_id):
            self.dropped_frames += 1
            return

        self._preroll.push(frame.pcm)
        if self._capturing:
            self._utterance.extend(frame.pcm)
            if bytes_to_ms(len(self._utterance)) > self.config.max_utterance_ms:
                # A stuck microphone must not become an unbounded bill.
                await self._end_utterance(reason="max_duration")
                return

        for window in self._windows.push(frame.pcm):
            await self._handle_vad_window(window)

    async def _handle_vad_window(self, window: bytes) -> None:
        decision = self.vad.push(window)
        window_ms = self.vad.settings.window_ms

        if decision.event is VadEvent.SPEECH_START:
            self._speech_ms = decision.run_ms
            await self._on_speech_start()
        elif decision.event is VadEvent.SPEECH_CONTINUE:
            self._speech_ms = decision.run_ms
            self._detector.on_speech()
        elif decision.event is VadEvent.SPEECH_END:
            await self._end_utterance(reason="speech_end", speech_ms=decision.run_ms)
        elif self._capturing:
            outcome = self._detector.on_silence(window_ms)
            if outcome.ended:
                await self._end_utterance(reason=outcome.reason, speech_ms=self._speech_ms)

    async def _on_speech_start(self) -> None:
        interrupting = self.machine.is_interruptible
        if interrupting:
            await self._barge_in()
        elif self.machine.state is TurnState.LISTENING:
            self.machine.fire(Trigger.SPEECH_START)
            await self._announce_state()

        self._begin_capture()

    def _begin_capture(self) -> None:
        self._capturing = True
        self._detector.reset()
        # Prepend the pre-roll so the utterance keeps its onset (ARCHITECTURE §5.5).
        self._utterance = bytearray(self._preroll.drain())

    async def _end_utterance(self, *, reason: str, speech_ms: int | None = None) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self._marks = TurnMarks(clock=self.clock)
        self._marks.mark(stage.SPEECH_END)
        audio = bytes(self._utterance)
        self._utterance = bytearray()

        # Measured from the VAD's confirmed speech run, NOT from the buffered audio: the 500 ms
        # pre-roll would otherwise satisfy this guard for every utterance, however brief, and a
        # cough would become a turn.
        spoken_ms = self._speech_ms if speech_ms is None else speech_ms
        self._speech_ms = 0
        if spoken_ms < self.config.min_utterance_ms:
            # Too short to be a question. Not an error, and not worth a turn index or a bill.
            if self.machine.can(Trigger.UTTERANCE_DISCARDED):
                self.machine.fire(Trigger.UTTERANCE_DISCARDED)
                await self._announce_state()
            return

        self._marks.mark(stage.TURN_END)
        transcript = await self._transcribe(audio)
        self._marks.mark(stage.STT_FINAL)

        if not transcript.text.strip() or self._is_backchannel(transcript.text):
            if self.machine.can(Trigger.UTTERANCE_DISCARDED):
                self.machine.fire(Trigger.UTTERANCE_DISCARDED)
                await self._announce_state()
            return

        await self.transport.send_control(
            ServerMessage.STT_FINAL,
            text=transcript.text,
            language=transcript.language_hint,
            confidence=transcript.confidence,
            turn_id=self.machine.turn_id,
        )

        utterance = transcript.text
        if self._pending_merge_text:
            # A continued thought, not a new question (ARCHITECTURE §5.6).
            utterance = f"{self._pending_merge_text} {utterance}".strip()
            self._pending_merge_text = ""
            log.info("voice.utterance_merged", session_id=str(self.session_id))

        language = transcript.language_hint or script_of(utterance)
        self._marks.mark(stage.LANGUAGE_DECIDED)

        self.machine.fire(Trigger.TURN_END)
        await self._announce_state()
        self._committed_at = self.clock()
        self._turn_task = asyncio.create_task(
            self._run_turn(utterance=utterance, language=language, reason=reason)
        )

    @staticmethod
    def _is_backchannel(text: str) -> bool:
        """Whether an utterance is an acknowledgement rather than a question.

        Checked on the transcript rather than the audio, because "haan" and "haan, lekin..." are
        acoustically similar and semantically opposite.
        """
        cleaned = text.strip().strip(".,!?।॥").casefold()
        return cleaned in BACKCHANNELS

    async def _transcribe(self, audio: bytes) -> FinalTranscript:
        async def frames() -> AsyncIterator[bytes]:
            yield audio

        final: FinalTranscript | None = None
        context = TranscriptionContext(language_hints=("en", "hi", "ta"))
        async for event in self.stt.transcribe_stream(frames(), context):
            if isinstance(event, PartialTranscript):
                await self.transport.send_control(
                    ServerMessage.STT_PARTIAL,
                    text=event.text,
                    stable_prefix_len=event.stable_prefix_chars,
                    language=event.language_hint,
                    turn_id=self.machine.turn_id,
                )
            elif isinstance(event, FinalTranscript):
                final = event
        return final or FinalTranscript(text="")

    # --- the turn ----------------------------------------------------------

    async def _run_turn(self, *, utterance: str, language: str, reason: str) -> None:
        self._ledger = PlaybackLedger()
        self._chunker.reset()
        self._audio_seq = 0
        self._voice = self._select_voice(language)
        delivery = _LedgerDelivery(ledger=self._ledger, pending_text=lambda: self._chunker.pending)

        stream = self.conversation.stream_turn(
            session_id=self.session_id,
            student_id=self.student_id,
            utterance=utterance,
            delivery=delivery,
            language=language,
            marks=self._marks.durations_ms(),
        )
        try:
            async for fragment, result in stream:
                if fragment:
                    self._marks.mark(stage.LLM_FIRST_TOKEN)
                    await self.transport.send_control(
                        ServerMessage.LLM_DELTA, text=fragment, turn_id=self.machine.turn_id
                    )
                    for chunk in self._chunker.push(fragment):
                        await self._speak(chunk.text)
                elif result is not None:
                    tail = self._chunker.flush()
                    if tail is not None:
                        await self._speak(tail.text)
                    await self._finish_turn(result_marks=result.latency_ms)
        except asyncio.CancelledError:
            # Barge-in. The ledger already holds what was heard; _barge_in does the accounting.
            raise
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

    async def _speak(self, text: str) -> None:
        if not text.strip():
            return
        if not self._marks.has(stage.FIRST_SENTENCE):
            self._marks.mark(stage.FIRST_SENTENCE)

        request = SynthesisRequest(
            text=text, voice=self._voice, sample_rate=self.config.tts_sample_rate
        )
        # Registered before synthesis starts: if the student interrupts mid-chunk, this text must
        # still appear in the record — as heard, partly heard, or unheard.
        self._ledger.begin_chunk(text)
        async for audio in self.tts.synthesize_stream(request):
            if not self._marks.has(stage.TTS_FIRST_BYTE):
                self._marks.mark(stage.TTS_FIRST_BYTE)
            if self.machine.state is TurnState.THINKING:
                self.machine.fire(Trigger.FIRST_AUDIO_QUEUED)
                await self._announce_state()
            await self.transport.send_audio(self.machine.turn_id, self._audio_seq, audio)
            self._marks.mark(stage.FIRST_AUDIO_SENT)
            self._audio_seq += 1
            self._ledger.extend_chunk(len(audio))

    async def _finish_turn(self, *, result_marks: dict[str, int]) -> None:
        self._marks.mark(stage.PLAYBACK_DRAINED)
        durations = {**result_marks, **self._marks.durations_ms()}
        await self.transport.send_control(
            ServerMessage.METRICS, turn_id=self.machine.turn_id, latency_ms=durations
        )
        if self.machine.state is TurnState.SPEAKING:
            self.machine.fire(Trigger.PLAYBACK_DRAINED)
        elif self.machine.can(Trigger.CANCELLED):
            # Nothing was ever spoken (an empty answer, or a refusal with no audio).
            self.machine.fire(Trigger.CANCELLED)
        await self._announce_state()
        self._detector.reset()

    # --- barge-in ----------------------------------------------------------

    async def _barge_in(self) -> None:
        """Stop talking, and make the record match what was heard.

        Inert when the mentor is not producing output: there is nothing to interrupt, and firing
        the cancellation transitions from another state would corrupt the machine.
        """
        if not self.machine.is_interruptible:
            log.debug("voice.barge_in_ignored", state=str(self.machine.state))
            return

        self._marks.mark(stage.BARGE_IN_DETECTED)
        interrupted_turn = self.machine.turn_id

        # Audible silence first: it is the only part the student perceives.
        await self.transport.send_control(ServerMessage.TTS_CANCEL, turn_id=interrupted_turn)
        self._marks.mark(stage.BARGE_IN_SILENCED)

        merged = self._should_merge()
        self.machine.fire(Trigger.SPEECH_START)
        await self._announce_state()

        await self._cancel_turn_task()
        # A final ACK may still be in flight; the ledger is resolved either way.
        await asyncio.sleep(self.config.ack_grace_ms / 1000)

        spoken = self._ledger.spoken_prefix()
        if merged:
            # Nothing was heard and the student is still mid-thought: carry their words forward
            # rather than splitting one question into two turns.
            self._pending_merge_text = ""

        log.info(
            "voice.barge_in",
            session_id=str(self.session_id),
            turn_id=interrupted_turn,
            played_ms=self._ledger.played_ms,
            total_audio_ms=self._ledger.total_audio_ms,
            spoken_chars=len(spoken),
            merged=merged,
            **self._marks.durations_ms(),
        )

        self.machine.fire(Trigger.CANCELLATION_COMPLETE)
        await self._announce_state()

    def _should_merge(self) -> bool:
        if self._ledger.played_ms > 0 or self._committed_at is None:
            return False
        elapsed_ms = (self.clock() - self._committed_at) * 1000
        return elapsed_ms <= self.config.merge_window_ms

    async def _cancel_turn_task(self) -> None:
        task = self._turn_task
        self._turn_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # --- inbound control ---------------------------------------------------

    async def handle_playback_ack(self, *, turn_id: int, played_ms: int) -> None:
        if turn_id != self.machine.turn_id:
            # An ACK for a turn that is over cannot change what was heard in this one.
            self.dropped_frames += 0
            return
        if played_ms > 0 and not self._marks.has(stage.FIRST_AUDIO_PLAYED):
            self._marks.mark(stage.FIRST_AUDIO_PLAYED)
        self._ledger.acknowledge(played_ms)

    async def handle_user_interrupt(self, *, turn_id: int) -> None:
        """An explicit stop (a button, not the voice). Same path as a detected barge-in."""
        if not self.machine.is_interruptible or turn_id != self.machine.turn_id:
            return
        await self._barge_in()
        # No utterance follows a button press, so return to listening rather than capturing.
        if self.machine.state is TurnState.USER_SPEAKING and self.machine.can(
            Trigger.UTTERANCE_DISCARDED
        ):
            self.machine.fire(Trigger.UTTERANCE_DISCARDED)
            await self._announce_state()

    async def handle_text(self, *, text: str) -> None:
        """The typed fallback inside a voice session (noisy room, no microphone permission)."""
        if self.machine.is_interruptible:
            await self._barge_in()
        if self.machine.state is TurnState.USER_SPEAKING:
            self.machine.fire(Trigger.UTTERANCE_DISCARDED)
        if self.machine.state is TurnState.LISTENING:
            self.machine.fire(Trigger.SPEECH_START)
        self._marks = TurnMarks(clock=self.clock)
        self._marks.mark(stage.SPEECH_END)
        self._marks.mark(stage.TURN_END)
        self._marks.mark(stage.STT_FINAL)
        self._marks.mark(stage.LANGUAGE_DECIDED)
        self.machine.fire(Trigger.TURN_END)
        await self._announce_state()
        self._committed_at = self.clock()
        self._turn_task = asyncio.create_task(
            self._run_turn(utterance=text, language=script_of(text), reason="typed")
        )

    async def wait_for_turn(self) -> None:
        """Test and shutdown helper: block until the in-flight turn finishes."""
        task = self._turn_task
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # --- helpers -----------------------------------------------------------

    def _select_voice(self, language: str) -> Voice:
        voices = self.tts.voices()
        for voice in voices:
            if voice.language == language:
                return voice
        # Fall back to the first voice rather than failing: a wrong-accent answer beats silence,
        # and the mismatch is visible in telemetry.
        if language not in {"en", "unknown"}:
            log.warning("voice.no_voice_for_language", language=language)
        return voices[0]

    async def _announce_state(self) -> None:
        await self.transport.send_control(
            ServerMessage.STATE, state=str(self.machine.state), turn_id=self.machine.turn_id
        )


__all__ = [
    "IllegalTransitionError",
    "Transport",
    "VoiceSession",
    "VoiceSessionConfig",
]
