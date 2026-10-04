"""Turn-end detection (ARCHITECTURE §4.3)."""

from __future__ import annotations

from app.voice.turn_detector import TurnDetector


def test_silence_shorter_than_the_threshold_does_not_end_a_turn() -> None:
    """A student thinking mid-sentence must not have their turn taken from them."""
    detector = TurnDetector(min_silence_ms=500)
    for _ in range(15):  # 480 ms
        assert detector.on_silence(32).ended is False


def test_silence_past_the_threshold_ends_the_turn() -> None:
    detector = TurnDetector(min_silence_ms=500)
    outcome = None
    for _ in range(16):  # 512 ms
        outcome = detector.on_silence(32)
    assert outcome is not None and outcome.ended is True
    assert outcome.reason == "silence"
    assert outcome.waited_ms >= 500


def test_resumed_speech_resets_the_silence_counter() -> None:
    detector = TurnDetector(min_silence_ms=500)
    for _ in range(15):
        detector.on_silence(32)
    detector.on_speech()
    for _ in range(15):
        assert detector.on_silence(32).ended is False


def test_semantic_endpointing_is_off_by_default() -> None:
    """It is a hypothesis with a switch (EXP-003), not a default."""
    detector = TurnDetector(min_silence_ms=500)
    outcome = detector.on_silence(300, stable_prefix="What is Kirchhoff's law?")
    assert outcome.ended is False


def test_semantic_endpointing_shortens_the_wait_on_a_complete_question() -> None:
    detector = TurnDetector(min_silence_ms=500, semantic_endpointing=True, semantic_silence_ms=250)
    outcome = detector.on_silence(260, stable_prefix="What is Kirchhoff's law?")
    assert outcome.ended is True
    assert outcome.reason == "semantic"


def test_semantic_endpointing_still_waits_on_an_incomplete_prefix() -> None:
    detector = TurnDetector(min_silence_ms=500, semantic_endpointing=True, semantic_silence_ms=250)
    outcome = detector.on_silence(260, stable_prefix="What is Kirchhoff's")
    assert outcome.ended is False
    # The full silence threshold still applies.
    assert detector.on_silence(300, stable_prefix="What is Kirchhoff's").ended is True


def test_a_devanagari_danda_counts_as_completion() -> None:
    detector = TurnDetector(semantic_endpointing=True, semantic_silence_ms=250)
    assert detector.on_silence(260, stable_prefix="यह क्या है।").ended is True


def test_a_very_short_prefix_is_never_treated_as_complete() -> None:
    """'Um.' should not end a turn just because it has a full stop."""
    detector = TurnDetector(semantic_endpointing=True, semantic_silence_ms=250)
    assert detector.on_silence(260, stable_prefix="Um.").ended is False
