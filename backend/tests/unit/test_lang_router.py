"""Language routing: script detection, romanized classification, stickiness, policy.

Conversation behaviour is tested as *sequences*, because stickiness and hysteresis only exist
across turns — a per-utterance accuracy number cannot express them. The per-utterance signal is
measured separately by the LID eval suite.
"""

from __future__ import annotations

import pytest

from app.agent.lang.hinglish import classify, tokenize
from app.agent.lang.lexicon import (
    AMBIGUOUS_TOKENS,
    ENGLISH_ONLY,
    HINDI_FUNCTION_WORDS,
    HINDI_ONLY,
)
from app.agent.lang.policy import response_directive, select_voice
from app.agent.lang.router import LanguageState, detect_explicit_request, route
from app.agent.lang.script import Script, profile
from app.providers.tts.fake import FakeTTSProvider

VOICES = FakeTTSProvider().voices()


# --- script ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Explain Kirchhoff's law", Script.LATIN),
        ("किरचॉफ का नियम समझाओ", Script.DEVANAGARI),
        ("கிர்ச்சாஃப் விதி", Script.TAMIL),
        ("displacement current का मतलब", Script.DEVANAGARI),
        ("3.5 kΩ", Script.LATIN),
        ("", Script.UNKNOWN),
        ("42 + 7", Script.UNKNOWN),
    ],
)
def test_script_profiling(text: str, expected: Script) -> None:
    assert profile(text).script is expected


def test_devanagari_decides_even_with_english_technical_terms() -> None:
    """Intra-sentence code-switching: a Hindi question keeps its technical terms in English."""
    assert profile("displacement current का मतलब क्या है").script is Script.DEVANAGARI


def test_a_single_devanagari_word_in_an_english_sentence_does_not_flip_the_script() -> None:
    """The threshold is 20% of alphabetic characters, and it is part of the metric definition
    in DATASET.md rather than a free parameter — one borrowed word is not a language switch."""
    assert profile("the displacement current density गुण").script is Script.LATIN


def test_latin_only_is_reported_as_such() -> None:
    assert profile("Kirchhoff ka voltage law").is_latin_only is True
    assert profile("किरचॉफ").is_latin_only is False


# --- lexicon hygiene -------------------------------------------------------


def test_the_two_lexicons_do_not_overlap() -> None:
    """Overlap would make the ratio arbitrary. Ambiguous words belong to neither side."""
    assert set() == HINDI_ONLY & ENGLISH_ONLY
    assert AMBIGUOUS_TOKENS <= HINDI_FUNCTION_WORDS | ENGLISH_ONLY | AMBIGUOUS_TOKENS


def test_ambiguous_tokens_are_evidence_for_neither_language() -> None:
    guess = classify("to me the")
    assert guess.language == "unknown"
    assert guess.evidence_tokens == 0
    assert set(guess.neutral_hits) == {"to", "me", "the"}


def test_technical_terms_are_not_english_evidence() -> None:
    """Otherwise every Hindi question about circuits reads as English."""
    guess = classify("KVL ka matlab kya hai")
    assert guess.language == "hi-Latn"
    assert "kvl" in guess.neutral_hits
    assert guess.english_hits == ()


def test_tokenize_lowercases_and_drops_punctuation() -> None:
    assert tokenize("Bhai, KVL kya hai?") == ["bhai", "kvl", "kya", "hai"]


# --- romanized classification ---------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kirchhoff ka voltage law samjhao", "hi-Latn"),
        ("Bhai KVL basically kya bol raha hai", "hi-Latn"),
        ("What does KVL actually mean", "en"),
        ("Can you explain this again please", "en"),
        ("enna panra epdi solla", "ta-Latn"),
    ],
)
def test_romanized_classification(text: str, expected: str) -> None:
    assert classify(text).language == expected


def test_no_scaffolding_means_unknown_not_english() -> None:
    """A bare technical phrase must not be guessed as English."""
    guess = classify("displacement current")
    assert guess.language == "unknown"
    assert guess.confidence == 0.0


def test_confidence_rises_with_evidence() -> None:
    weak = classify("Actually continue")
    strong = classify("Yaar ye concept samajh nahi aa raha hai phir se batao")
    assert weak.confidence < strong.confidence
    assert strong.confidence > 0.8


def test_a_single_evidence_token_is_low_confidence() -> None:
    """One token must not redefine a conversation; the router prefers its prior."""
    assert classify("Actually never mind continue").confidence <= 0.3


def test_romanized_tamil_confidence_is_capped() -> None:
    """Tamil is deferred past the MVP and this path has had no evaluation (M-01)."""
    assert classify("enna panra epdi solla theriyala").confidence <= 0.5


def test_a_decision_can_be_explained_by_its_tokens() -> None:
    """Legibility is why a lexicon was chosen over a model — failures must be diagnosable."""
    explanation = classify("Bhai KVL kya hai").explain()
    assert "hi=" in explanation and "kya" in explanation


# --- explicit requests -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Can you explain in Hindi please", "hi"),
        ("Hindi mein batao", "hi"),
        ("Answer in English from now on", "en"),
        ("English mein bolo", "en"),
        ("Please explain in Tamil", "ta"),
        ("तमिल में बताओ", "ta"),
        ("हिंदी में समझाओ", "hi"),
        ("What is KVL", None),
        ("The Hindi film industry", None),
    ],
)
def test_explicit_request_detection(text: str, expected: str | None) -> None:
    assert detect_explicit_request(text) == expected


def test_an_explicit_request_wins_immediately_and_locks() -> None:
    decision = route("Please explain in Hindi", LanguageState(sticky="en"))
    assert decision.language == "hi"
    assert decision.source == "explicit"
    assert decision.switched is True
    assert decision.state.locked is True


# --- stickiness and hysteresis ---------------------------------------------


def test_a_non_latin_script_switches_immediately() -> None:
    """No hysteresis: there is nothing to be unsure about."""
    decision = route("किरचॉफ का नियम समझाओ", LanguageState(sticky="en"))
    assert decision.language == "hi"
    assert decision.source == "script"
    assert decision.switched is True


def test_a_romanized_switch_needs_two_consecutive_turns() -> None:
    """The mentor mirrors immediately, but the prior moves only on the second turn.

    Answering in the student's language at once is right; moving the conversation's default on one
    utterance is how a language router starts flapping.
    """
    state = LanguageState(sticky="en")

    first = route("Bhai ye samajh nahi aa raha phir se batao", state)
    assert first.language == "hi-Latn", "the answer mirrors the student immediately"
    assert first.switched is False, "but the prior has not moved yet"
    assert first.state.sticky == "en"
    assert first.state.pending == "hi-Latn"

    second = route("Aur KCL ka matlab kya hai", first.state)
    assert second.switched is True
    assert second.state.sticky == "hi-Latn"
    assert second.state.pending is None


def test_a_one_off_utterance_does_not_move_the_prior() -> None:
    state = LanguageState(sticky="hi-Latn")
    first = route("What does this mean", state)
    assert first.state.sticky == "hi-Latn"
    # Then back to Hinglish: the half-formed challenge is cleared.
    second = route("Phir se samjhao thoda dheere", first.state)
    assert second.state.pending is None
    assert second.state.sticky == "hi-Latn"


def test_a_low_signal_utterance_holds_the_prior() -> None:
    """ "ok" must not redefine the conversation."""
    state = LanguageState(sticky="hi-Latn")
    decision = route("ok", state)
    assert decision.language == "hi-Latn"
    assert decision.source == "sticky"
    assert decision.state == state


def test_a_bare_technical_phrase_holds_the_prior() -> None:
    state = LanguageState(sticky="hi-Latn")
    assert route("displacement current", state).language == "hi-Latn"


def test_two_indic_scripts_in_one_utterance_hold_the_prior() -> None:
    """Rare, and not something to guess at."""
    state = LanguageState(sticky="en")
    decision = route("किरचॉफ கிர்ச்சாஃப்", state)
    assert decision.source == "sticky"
    assert decision.language == "en"


def test_a_full_conversation_switches_and_settles() -> None:
    turns = [
        ("Explain Kirchhoff's voltage law", "en"),
        ("Bhai ye samajh nahi aa raha, phir se batao", "hi-Latn"),
        ("Aur KCL ka matlab kya hai", "hi-Latn"),
        ("ok", "hi-Latn"),
        ("किरचॉफ का नियम समझाओ", "hi"),
        ("Actually can you explain in english", "en"),
        ("What about mesh analysis", "en"),
    ]
    state = LanguageState()
    for text, expected in turns:
        decision = route(text, state)
        state = decision.state
        assert decision.language == expected, f"{text!r} -> {decision.explain()}"


# --- policy ----------------------------------------------------------------


def test_every_routed_language_has_a_response_directive() -> None:
    for language in ("en", "hi", "hi-Latn", "ta", "mixed"):
        directive = response_directive(language)
        assert directive and len(directive) > 20


def test_the_hinglish_directive_forbids_normalising_the_student() -> None:
    """Answering Hinglish in formal Hindi is a specific, common way to get this wrong."""
    directive = response_directive("hi-Latn") or ""
    assert "Latin script" in directive
    assert "formal" in directive


def test_directives_keep_technical_terms_in_english() -> None:
    for language in ("hi", "hi-Latn", "ta", "mixed"):
        assert "technical" in (response_directive(language) or "")


def test_an_unrouted_language_has_no_directive() -> None:
    """Nothing is asserted about a language the system does not route."""
    assert response_directive("ml") is None


@pytest.mark.parametrize(
    ("language", "voice_language"),
    [("en", "en"), ("hi", "hi"), ("hi-Latn", "hi"), ("ta", "ta"), ("mixed", "hi")],
)
def test_voice_selection(language: str, voice_language: str) -> None:
    plan = select_voice(language, VOICES)
    assert plan.voice.language == voice_language
    assert plan.voice_matched_language is True


def test_romanized_hindi_requests_transliteration() -> None:
    """Romanized Hindi through an Indic voice is read with English phonetics (EXP-006, R-05)."""
    assert select_voice("hi-Latn", VOICES).transliterate_to_devanagari is True
    assert select_voice("hi", VOICES).transliterate_to_devanagari is False


def test_an_unknown_language_falls_back_and_says_so() -> None:
    """Reporting a fallback as a match would hide the gap from the only place it is noticed."""
    plan = select_voice("ml", VOICES)
    assert plan.voice_matched_language is False
    assert plan.voice is VOICES[0]


def test_a_missing_voice_for_a_routed_language_is_reported() -> None:
    english_only = (VOICES[0],)
    plan = select_voice("ta", english_only)
    assert plan.voice_matched_language is False
