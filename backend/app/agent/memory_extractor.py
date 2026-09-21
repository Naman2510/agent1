"""`MemoryExtractor` (ARCHITECTURE §12, ADR-0012): after a turn, an async, off-the-critical-path
call proposes structured deltas — never prose — about what the exchange revealed regarding the
student's mastery and preferences.

Two write rules keep one utterance from rewriting a student's record:

- **EWMA, never replacement.** A topic signal blends into `student_topics.mastery` at
  `CONVERSATIONAL_ALPHA = 0.1` — a third of the trust `update_student_progress`'s graded quiz
  evidence gets (`alpha=0.3`, `app/agent/tools/progress.py`), because an inferred conversational
  signal deserves less weight than a graded answer.
- **Confidence gating.** A delta below `CONFIDENCE_THRESHOLD` is recorded to `memory_events` for
  the audit trail but never applied.

Every delta — applied or not — is written to `memory_events` with `EXTRACTOR_VERSION`, so a wrong
profile is explainable and a changed extractor is a versioned, replayable event (ADR-0012).

Forced structured output (`tool_choice`) gets the shape right when the model cooperates, but
`strict` tool schemas are an Anthropic API-side guarantee (ARCHITECTURE §8.3) — nothing in this
process enforces it against a provider that does not actually implement it (`FakeLLMProvider`
hands back exactly the arguments a test script gives it, unvalidated). Output is therefore still
validated in Python before anything is written, and a malformed proposal is rejected and logged
rather than partially applied, exactly as ADR-0012 requires regardless of which layer provides it.
"""

from __future__ import annotations

import uuid
from typing import Literal

import structlog
from pydantic import Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.tools.base import ToolInput
from app.db.models import MemoryKind
from app.db.repositories.memory import (
    MemoryEventRepository,
    StudentProfileRepository,
    StudentTopicRepository,
)
from app.providers.base import ProviderError
from app.providers.llm.base import (
    Effort,
    LLMProvider,
    LLMRequest,
    SystemBlock,
    ToolCall,
    ToolCallDelta,
    ToolSpec,
    TurnMessage,
)

log = structlog.get_logger(__name__)

EXTRACTOR_VERSION = "memory-extractor-v1"
CONVERSATIONAL_ALPHA = 0.1
CONFIDENCE_THRESHOLD = 0.5

# A documented heuristic (ARCHITECTURE §12 calls mastery exactly that, not knowledge tracing): the
# extractor reports what it can actually judge from one exchange — a small, named vocabulary — and
# this is the one place that vocabulary is translated into the numeric sample apply_ewma needs.
# The values are a considered ordering (struggled < confused < improved < confident), not a
# calibrated scale; recalibrating them is a config change, not a correctness fix.
_SIGNAL_SAMPLE: dict[str, float] = {
    "struggled": 0.2,
    "confused": 0.35,
    "improved": 0.7,
    "confident": 0.9,
}


class TopicSignal(ToolInput):
    subject: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    # Must match _SIGNAL_SAMPLE's keys exactly — Pydantic rejects anything else with a clean
    # ValidationError (caught in _propose) rather than a KeyError from the sample lookup later.
    signal: Literal["struggled", "confused", "improved", "confident"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=1, max_length=280)


class PreferenceSignal(ToolInput):
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ProposedMemoryDeltas(ToolInput):
    topic_signals: list[TopicSignal] = Field(default_factory=list, max_length=5)
    preference_signals: list[PreferenceSignal] = Field(default_factory=list, max_length=5)


PROPOSE_MEMORY_DELTAS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "topic_signals": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "topic": {"type": "string"},
                    "signal": {"type": "string", "enum": list(_SIGNAL_SAMPLE)},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "evidence": {
                        "type": "string",
                        "description": "A short quote or paraphrase from this exchange.",
                    },
                },
                "required": ["subject", "topic", "signal", "confidence", "evidence"],
            },
        },
        "preference_signals": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "e.g. 'explanation_style'."},
                    "value": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["key", "value", "confidence"],
            },
        },
    },
    "required": ["topic_signals", "preference_signals"],
}

PROPOSE_MEMORY_DELTAS_TOOL = ToolSpec(
    name="propose_memory_deltas",
    description="Record what this exchange reveals about the student's mastery and preferences.",
    input_schema=PROPOSE_MEMORY_DELTAS_SCHEMA,
    strict=True,
)

_EXTRACTOR_SYSTEM = SystemBlock(
    text=(
        "You will be shown one exchange from a tutoring conversation. Call "
        "propose_memory_deltas exactly once to record what it reveals about the student's "
        "mastery of specific topics and their learning preferences — call it with two empty "
        "lists if there is nothing worth noting, rather than not calling it. Only propose a "
        "topic_signal when the exchange itself is real evidence (the student got something "
        "wrong, asked for a third re-explanation, or clearly demonstrated understanding); never "
        "invent a subject or topic that was not actually discussed. Only propose a "
        "preference_signal for an explicit or strongly implied preference about how they like "
        "things explained. `confidence` is your own confidence in the signal, not a mastery score."
    ),
    cacheable=False,
)


class MemoryExtractor:
    def __init__(self, llm: LLMProvider, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._llm = llm
        self._session_factory = session_factory

    async def extract_and_apply(
        self,
        *,
        student_id: uuid.UUID,
        session_id: uuid.UUID,
        message_id: uuid.UUID | None,
        utterance: str,
        reply: str,
    ) -> None:
        deltas = await self._propose(utterance, reply)
        if deltas is None or not (deltas.topic_signals or deltas.preference_signals):
            return

        async with self._session_factory() as db:
            events = MemoryEventRepository(db)
            topics = StudentTopicRepository(db)
            profiles = StudentProfileRepository(db)

            for signal in deltas.topic_signals:
                await self._apply_topic_signal(
                    signal,
                    student_id=student_id,
                    session_id=session_id,
                    message_id=message_id,
                    events=events,
                    topics=topics,
                )
            for preference in deltas.preference_signals:
                await self._apply_preference_signal(
                    preference,
                    student_id=student_id,
                    session_id=session_id,
                    message_id=message_id,
                    events=events,
                    profiles=profiles,
                )
            await db.commit()

    async def _apply_topic_signal(
        self,
        signal: TopicSignal,
        *,
        student_id: uuid.UUID,
        session_id: uuid.UUID,
        message_id: uuid.UUID | None,
        events: MemoryEventRepository,
        topics: StudentTopicRepository,
    ) -> None:
        payload = signal.model_dump()
        if signal.confidence < CONFIDENCE_THRESHOLD:
            await events.record(
                student_id=student_id,
                session_id=session_id,
                message_id=message_id,
                kind=MemoryKind.OBSERVATION,
                payload=payload,
                confidence=signal.confidence,
                extractor_version=EXTRACTOR_VERSION,
                applied=False,
                rejection_reason="confidence below threshold",
            )
            return
        await topics.apply_ewma(
            student_id,
            signal.subject,
            signal.topic,
            sample=_SIGNAL_SAMPLE[signal.signal],
            alpha=CONVERSATIONAL_ALPHA,
        )
        await events.record(
            student_id=student_id,
            session_id=session_id,
            message_id=message_id,
            kind=MemoryKind.TOPIC_UPDATE,
            payload=payload,
            confidence=signal.confidence,
            extractor_version=EXTRACTOR_VERSION,
            applied=True,
        )

    async def _apply_preference_signal(
        self,
        preference: PreferenceSignal,
        *,
        student_id: uuid.UUID,
        session_id: uuid.UUID,
        message_id: uuid.UUID | None,
        events: MemoryEventRepository,
        profiles: StudentProfileRepository,
    ) -> None:
        payload = preference.model_dump()
        if preference.confidence < CONFIDENCE_THRESHOLD:
            await events.record(
                student_id=student_id,
                session_id=session_id,
                message_id=message_id,
                kind=MemoryKind.OBSERVATION,
                payload=payload,
                confidence=preference.confidence,
                extractor_version=EXTRACTOR_VERSION,
                applied=False,
                rejection_reason="confidence below threshold",
            )
            return
        if preference.key == "explanation_style":
            await profiles.apply_update(student_id, explanation_style=preference.value)
        else:
            await profiles.apply_update(
                student_id, learning_preferences_patch={preference.key: preference.value}
            )
        await events.record(
            student_id=student_id,
            session_id=session_id,
            message_id=message_id,
            kind=MemoryKind.PROFILE_UPDATE,
            payload=payload,
            confidence=preference.confidence,
            extractor_version=EXTRACTOR_VERSION,
            applied=True,
        )

    async def _propose(self, utterance: str, reply: str) -> ProposedMemoryDeltas | None:
        request = LLMRequest(
            system=[_EXTRACTOR_SYSTEM],
            messages=[TurnMessage(role="user", text=f"Student: {utterance}\nMentor: {reply}")],
            tools=[PROPOSE_MEMORY_DELTAS_TOOL],
            tool_choice=PROPOSE_MEMORY_DELTAS_TOOL.name,
            max_output_tokens=512,
            effort=Effort.LOW,
        )
        call: ToolCall | None = None
        try:
            async for event in self._llm.stream(request):
                if isinstance(event, ToolCallDelta):
                    call = event.call
        except ProviderError:
            # Never the reason a turn fails — this runs after the turn has already been streamed
            # and stored, so the only cost of a provider hiccup here is one skipped extraction.
            log.warning("memory_extractor.provider_failed", exc_info=True)
            return None

        if call is None or call.name != PROPOSE_MEMORY_DELTAS_TOOL.name:
            log.warning("memory_extractor.no_tool_call")
            return None
        try:
            return ProposedMemoryDeltas.model_validate(call.arguments)
        except ValidationError:
            log.warning("memory_extractor.malformed_output", raw=call.arguments)
            return None
