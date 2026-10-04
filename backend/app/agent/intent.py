"""`IntentGate` (ARCHITECTURE §8.2): a cheap, low-effort classification call that maps one
utterance to a coarse intent, which in turn maps to a tool allowlist.

Exposing all seven tools on every turn degrades selection accuracy and wastes prompt tokens (spec
§12). This is a precision/recall trade, so it must earn its place by measurement (the agent eval
suite reports task completion gated vs. ungated) rather than being assumed to help.
"""

from __future__ import annotations

import enum

import structlog

from app.providers.base import ProviderError
from app.providers.llm.base import (
    Effort,
    LLMProvider,
    LLMRequest,
    StreamCompleted,
    SystemBlock,
    TextDelta,
    TurnMessage,
)

log = structlog.get_logger(__name__)


class Intent(enum.StrEnum):
    QUESTION = "question"
    DOUBT = "doubt"
    QUIZ_REQUEST = "quiz_request"
    PROGRESS_REQUEST = "progress_request"
    REVISION_REQUEST = "revision_request"
    STUDY_PLAN = "study_plan"
    CLARIFICATION = "clarification"
    CASUAL = "casual"


# A question with no course-material grounding is still safer answered from search_knowledge than
# from memory, so an unparseable classification degrades to the same allowlist as an ordinary
# question rather than to "no tools at all" — a silent classifier failure should cost some
# precision, not silently disable the mentor's ability to look anything up.
DEFAULT_INTENT = Intent.QUESTION

INTENT_TOOLS: dict[Intent, frozenset[str]] = {
    Intent.QUESTION: frozenset({"search_knowledge"}),
    Intent.DOUBT: frozenset({"search_knowledge"}),
    # update_student_progress lives here rather than in a dedicated "answering a quiz" intent
    # because the classifier is single-utterance, stateless (see classify() below) — it has no way
    # to know a quiz is in progress from the bare answer alone. Grouping grading with the request
    # that starts a quiz is an honest compromise, not a full fix: a short, out-of-context reply
    # ("5 ohms") may still not read as quiz_request to the classifier and can fall through to
    # another intent with no path to update_student_progress. Tracking "this session has an open
    # quiz" and overriding the gate while one is pending is real future work (see ROADMAP.md).
    Intent.QUIZ_REQUEST: frozenset(
        {"generate_quiz", "update_student_progress", "search_knowledge"}
    ),
    Intent.PROGRESS_REQUEST: frozenset({"get_student_progress", "retrieve_previous_conversation"}),
    Intent.REVISION_REQUEST: frozenset(
        {"get_student_progress", "create_study_plan", "search_knowledge"}
    ),
    Intent.STUDY_PLAN: frozenset({"create_study_plan", "get_study_plan", "get_student_progress"}),
    Intent.CLARIFICATION: frozenset(),
    Intent.CASUAL: frozenset(),
}

_LABELS = ", ".join(intent.value for intent in Intent)

_CLASSIFIER_SYSTEM = SystemBlock(
    text=(
        "Classify the student's message into exactly one label, and reply with only that label "
        "and nothing else — no punctuation, no explanation.\n\n"
        f"Labels: {_LABELS}\n\n"
        "question: a course-content question needing an explanation.\n"
        "doubt: a follow-up expressing confusion about something already discussed.\n"
        "quiz_request: asking to be quizzed or tested, or reporting/answering quiz questions "
        "already asked.\n"
        "progress_request: asking how they are doing, or what they are weak at.\n"
        "revision_request: asking what to revise or focus on.\n"
        "study_plan: asking for a study schedule or plan.\n"
        "clarification: asking the mentor to repeat or clarify its own last answer.\n"
        "casual: greetings, thanks, or anything not about coursework."
    ),
    cacheable=False,
)


class IntentGate:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def classify(self, utterance: str) -> Intent:
        request = LLMRequest(
            system=[_CLASSIFIER_SYSTEM],
            messages=[TurnMessage(role="user", text=utterance)],
            max_output_tokens=8,
            effort=Effort.LOW,
        )
        text = ""
        try:
            async for event in self._llm.stream(request):
                if isinstance(event, TextDelta):
                    text += event.text
                elif isinstance(event, StreamCompleted) and event.stop_reason == "refusal":
                    log.warning("intent_gate.refusal")
                    return DEFAULT_INTENT
        except ProviderError as exc:
            # This call must never be the reason a turn fails outright — a provider hiccup here
            # degrades to the same safe default an unparseable response gets, not a crashed turn.
            log.warning("intent_gate.provider_failed", provider=exc.provider, exc_info=True)
            return DEFAULT_INTENT
        return _parse(text)

    def tools_for(self, intent: Intent) -> frozenset[str]:
        return INTENT_TOOLS[intent]


def _parse(raw: str) -> Intent:
    cleaned = raw.strip().strip(".\"'").lower().replace(" ", "_").replace("-", "_")
    try:
        return Intent(cleaned)
    except ValueError:
        log.warning("intent_gate.unparseable", raw=raw)
        return DEFAULT_INTENT
