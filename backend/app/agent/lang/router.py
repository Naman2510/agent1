"""Language routing with sticky session state (ADR-0011).

The user must never pick a language per utterance, mid-conversation switching must work, and the
system must not flap. Those three pull against each other, so the policy is layered — cheapest and
most certain signal first:

1. **An explicit request** ("in Hindi", "hindi mein", "தமிழில்") wins immediately and persists.
   It is the one case where the student has actually stated an intention.
2. **A dominant non-Latin script** decides immediately. There is no ambiguity to weigh.
3. **Latin script** goes to the romanized classifier. Its answer is taken only when it is
   confident.
4. **Otherwise the session's sticky prior** holds. A two-word utterance must not redefine the
   conversation.

Hysteresis: the prior changes only after two consecutive turns disagree with it — unless the
signal was an explicit request or a script decision, which are immediate. The cost is one turn of
lag when following a genuine switch; the benefit is not switching language because someone said
"ok". That trade is a UX judgement, and it is recorded here rather than buried in a threshold.

The router is pure: it takes the current state and returns a new one. The session owns storage,
which keeps this testable without Redis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.agent.lang.hinglish import RomanizedGuess, classify
from app.agent.lang.script import Script, ScriptProfile, profile

# Languages the system routes between. "mixed" is a real outcome, not a failure.
LANGUAGES = ("en", "hi", "hi-Latn", "ta", "mixed")

# Confidence at or above which the romanized classifier's answer is taken over the sticky prior.
ROMANIZED_TRUST = 0.4

# Explicit requests. Matched on the whole utterance, case-folded. Deliberately narrow: a false
# positive here changes the language for the rest of the session.
_EXPLICIT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:in|speak|talk|reply|answer|explain)\s+(?:in\s+)?hindi\b"), "hi"),
    (re.compile(r"\bhindi\s+(?:me|mein|m)\b"), "hi"),
    (re.compile(r"\bhindi\s+(?:me|mein)\s+(?:bata|batao|samjha|samjhao|bolo)\b"), "hi"),
    (re.compile(r"\b(?:in|speak|talk|reply|answer|explain)\s+(?:in\s+)?english\b"), "en"),
    (re.compile(r"\benglish\s+(?:me|mein|m)\b"), "en"),
    (re.compile(r"\b(?:in|speak|talk|reply|answer|explain)\s+(?:in\s+)?tamil\b"), "ta"),
    (re.compile(r"\btamil\s+(?:la|le|il)\b"), "ta"),
    # "Tamil" written in Devanagari must map to Tamil, not Hindi. It was in the Hindi
    # alternation originally, so "तमिल में बताओ" — a request *for Tamil* — routed to Hindi.
    (re.compile(r"तमिल|तमिळ"), "ta"),
    (re.compile(r"हिंदी\s+में|हिन्दी\s+में|हिंदी\s+मे"), "hi"),
    (re.compile(r"தமிழில்|தமிழ்ல|தமிழில"), "ta"),
    (re.compile(r"ஆங்கிலத்தில்"), "en"),
)


@dataclass(frozen=True)
class LanguageState:
    """The sticky prior, carried across turns.

    `pending` and `pending_streak` implement the hysteresis: a challenger must win twice.
    """

    sticky: str = "en"
    pending: str | None = None
    pending_streak: int = 0
    # True once the student has stated a language explicitly; the prior then stops drifting.
    locked: bool = False


@dataclass(frozen=True)
class LanguageDecision:
    language: str
    script: Script
    source: str  # explicit | script | romanized | sticky
    confidence: float
    state: LanguageState
    switched: bool = False
    guess: RomanizedGuess | None = None

    def explain(self) -> str:
        detail = f" [{self.guess.explain()}]" if self.guess else ""
        return (
            f"{self.language} via {self.source} (conf {self.confidence:.2f}, "
            f"script {self.script}, sticky {self.state.sticky})" + detail
        )


def detect_explicit_request(text: str) -> str | None:
    lowered = text.casefold()
    for pattern, language in _EXPLICIT_PATTERNS:
        if pattern.search(lowered):
            return language
    return None


def route(text: str, state: LanguageState | None = None) -> LanguageDecision:
    current = state or LanguageState()
    script_profile = profile(text)

    # 1. An explicit request: immediate, and it locks the prior.
    explicit = detect_explicit_request(text)
    if explicit is not None:
        new_state = LanguageState(sticky=explicit, pending=None, pending_streak=0, locked=True)
        return LanguageDecision(
            language=explicit,
            script=script_profile.script,
            source="explicit",
            confidence=1.0,
            state=new_state,
            switched=explicit != current.sticky,
        )

    # 2. A dominant non-Latin script: immediate, no hysteresis. There is nothing to be unsure of.
    if script_profile.script is Script.DEVANAGARI:
        return _immediate("hi", script_profile, current)
    if script_profile.script is Script.TAMIL:
        return _immediate("ta", script_profile, current)
    if script_profile.script is Script.MIXED:
        # Two Indic scripts in one utterance. Rare, and not something to guess at: hold the prior.
        return _sticky(script_profile, current, confidence=0.2)

    # 3. Latin script: ask the romanized classifier, and believe it only when it is confident.
    guess = classify(text)
    if guess.confidence >= ROMANIZED_TRUST and guess.language in {
        "en",
        "hi-Latn",
        "mixed",
        "ta-Latn",
    }:
        candidate = "ta" if guess.language == "ta-Latn" else guess.language
        return _with_hysteresis(candidate, script_profile, current, guess)

    # 4. Not enough evidence. The prior holds — this is the path that stops a "haan" from
    #    redefining the conversation.
    return _sticky(script_profile, current, confidence=guess.confidence, guess=guess)


def _immediate(
    language: str, script_profile: ScriptProfile, current: LanguageState
) -> LanguageDecision:
    new_state = LanguageState(
        sticky=language,
        pending=None,
        pending_streak=0,
        locked=current.locked,
    )
    return LanguageDecision(
        language=language,
        script=script_profile.script,
        source="script",
        confidence=script_profile.dominant_share,
        state=new_state,
        switched=language != current.sticky,
    )


def _sticky(
    script_profile: ScriptProfile,
    current: LanguageState,
    *,
    confidence: float,
    guess: RomanizedGuess | None = None,
) -> LanguageDecision:
    return LanguageDecision(
        language=current.sticky,
        script=script_profile.script,
        source="sticky",
        confidence=confidence,
        state=current,
        switched=False,
        guess=guess,
    )


def _with_hysteresis(
    candidate: str,
    script_profile: ScriptProfile,
    current: LanguageState,
    guess: RomanizedGuess,
) -> LanguageDecision:
    if candidate == current.sticky:
        # Agreement clears any half-formed challenge.
        state = replace(current, pending=None, pending_streak=0)
        return LanguageDecision(
            language=candidate,
            script=script_profile.script,
            source="romanized",
            confidence=guess.confidence,
            state=state,
            switched=False,
            guess=guess,
        )

    streak = current.pending_streak + 1 if current.pending == candidate else 1
    if streak >= 2:
        # Two turns in a row: the switch is real.
        state = LanguageState(
            sticky=candidate, pending=None, pending_streak=0, locked=current.locked
        )
        return LanguageDecision(
            language=candidate,
            script=script_profile.script,
            source="romanized",
            confidence=guess.confidence,
            state=state,
            switched=True,
            guess=guess,
        )

    # First disagreement: answer in the *candidate's* language for this turn — mirroring the
    # student is the right immediate behaviour — but do not move the prior yet.
    state = replace(current, pending=candidate, pending_streak=streak)
    return LanguageDecision(
        language=candidate,
        script=script_profile.script,
        source="romanized",
        confidence=guess.confidence,
        state=state,
        switched=False,
        guess=guess,
    )
