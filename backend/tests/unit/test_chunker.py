"""Sentence chunking. Every rule here is audible when it breaks."""

from __future__ import annotations

from app.voice.chunker import SentenceChunker


def _chunks(text: str, *, delta: int = 7, **kwargs: int) -> list[str]:
    """Feed text in small deltas, as a token stream would arrive."""
    chunker = SentenceChunker(**kwargs)  # type: ignore[arg-type]
    out: list[str] = []
    for start in range(0, len(text), delta):
        out.extend(c.text for c in chunker.push(text[start : start + delta]))
    tail = chunker.flush()
    if tail is not None:
        out.append(tail.text)
    return out


def test_sentences_are_split_on_terminal_punctuation() -> None:
    assert _chunks(
        "The first sentence is long enough. The second sentence is also long enough. Done."
    ) == [
        "The first sentence is long enough.",
        "The second sentence is also long enough.",
        "Done.",
    ]


def test_very_short_consecutive_sentences_are_merged_for_prosody() -> None:
    """Deliberate: a stream of three-word chunks sounds chopped up when spoken.

    `min_chunk_chars` applies from the second chunk onward — the first is allowed to be tiny
    because it alone determines time-to-first-audio.
    """
    assert _chunks("Yes. No. Maybe so.") == ["Yes.", "No. Maybe so."]


def test_the_first_chunk_is_emitted_early_to_start_audio_sooner() -> None:
    """TTFA is decided entirely by the first chunk (EXP-005)."""
    chunker = SentenceChunker()
    emitted = chunker.push("Sure. ")
    assert [c.text for c in emitted] == ["Sure."]
    assert emitted[0].reason == "terminal"


def test_a_long_opening_clause_breaks_at_a_comma_before_any_terminal_arrives() -> None:
    """The case that matters for TTFA: tokens are still streaming and no full stop has arrived.

    A terminal always wins when one is already present — there is no latency to gain by splitting
    text we already hold.
    """
    chunker = SentenceChunker(first_chunk_max_words=6)
    out = chunker.push("Kirchhoff's voltage law says that around any closed loop, the sum")
    assert out, "a long opener must not wait for a full stop that has not arrived"
    assert out[0].reason == "clause"
    assert out[0].text.endswith(",")


def test_a_terminal_already_in_the_buffer_beats_a_clause_break() -> None:
    chunker = SentenceChunker(first_chunk_max_words=6)
    out = chunker.push("Around any closed loop, the sum of voltages is zero.")
    assert [c.reason for c in out] == ["terminal"]


def test_a_decimal_point_is_not_a_sentence_end() -> None:
    """Splitting here makes the mentor say 'three point' ... 'five kilohms'."""
    assert _chunks("The resistance is 3.5 kilohms exactly.") == [
        "The resistance is 3.5 kilohms exactly."
    ]


def test_a_comma_thousands_separator_is_not_a_break() -> None:
    assert _chunks("It draws 1,000 milliamps in total.") == ["It draws 1,000 milliamps in total."]


def test_abbreviations_do_not_end_a_sentence() -> None:
    assert _chunks("See e.g. the lecture notes for more.") == [
        "See e.g. the lecture notes for more."
    ]
    assert _chunks("Ask Dr. Sharma about it tomorrow.") == ["Ask Dr. Sharma about it tomorrow."]


def test_an_initial_does_not_end_a_sentence() -> None:
    assert _chunks("This is J. C. Maxwell's fourth equation here.") == [
        "This is J. C. Maxwell's fourth equation here."
    ]


def test_the_devanagari_danda_is_a_sentence_end() -> None:
    """A chunker that only knows '.?!' reads a whole Hindi paragraph in one breath."""
    out = _chunks("यह पहला वाक्य है। यह दूसरा वाक्य है।")
    assert out == ["यह पहला वाक्य है।", "यह दूसरा वाक्य है।"]


def test_tamil_text_splits_on_the_full_stop() -> None:
    out = _chunks("இது முதல் வாக்கியம். இது இரண்டாவது வாக்கியம்.")
    assert len(out) == 2
    assert out[0].endswith(".")


def test_a_question_mark_ends_a_chunk() -> None:
    assert _chunks("Do you follow so far? Then let us continue.") == [
        "Do you follow so far?",
        "Then let us continue.",
    ]


def test_a_very_long_clause_is_broken_rather_than_stalling_audio() -> None:
    """A max-wait break, so one run-on sentence cannot hold the speaker silent."""
    text = "and then " * 60
    out = _chunks(text, max_chunk_chars=120)
    assert len(out) > 1
    # The cut must never land inside a word.
    assert all(not c.endswith("an") and not c.endswith("the") for c in out[:-1])
    assert all(c.strip() == c for c in out)


def test_a_max_wait_break_falls_on_a_space() -> None:
    chunker = SentenceChunker(max_chunk_chars=40, min_chunk_chars=10)
    out = chunker.push("x" * 5 + " " + "word " * 20)
    assert out
    assert not out[0].text.endswith("wor"), "a max-wait cut must land on a space"


def test_no_text_is_lost_or_duplicated() -> None:
    """The strongest invariant: chunking is a partition of the answer."""
    source = (
        "Sure. Kirchhoff's voltage law says the sum of potential differences around any "
        "closed loop is 3.5 volts, or zero in an ideal loop. Does that help? "
        "यह हिंदी वाक्य है। Let us continue."
    )
    rejoined = " ".join(_chunks(source, delta=3))
    # Whitespace is normalised by the chunker, so compare on non-space characters.
    assert rejoined.replace(" ", "") == source.replace(" ", "")


def test_flush_returns_nothing_when_there_is_nothing_pending() -> None:
    chunker = SentenceChunker()
    assert chunker.flush() is None
    chunker.push("   ")
    assert chunker.flush() is None


def test_chunk_indices_increase() -> None:
    chunker = SentenceChunker()
    out = chunker.push("One. Two. Three.")
    assert [c.index for c in out] == list(range(len(out)))


def test_pending_text_is_visible_before_it_is_emitted() -> None:
    """The session reports unsynthesised text as part of the unheard remainder."""
    chunker = SentenceChunker()
    chunker.push("An unfinished sentence without a terminal")
    assert "unfinished" in chunker.pending
