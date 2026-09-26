"""The playback ledger — the mechanism behind the barge-in invariant (Gate 0 finding C-03).

If these are wrong, the mentor refers back to explanations the student never heard, and it
presents as the AI being confusing rather than as an error.
"""

from __future__ import annotations

from app.voice.audio import ms_to_bytes
from app.voice.playback import PlaybackLedger

RATE = 24_000  # the synthesised audio's rate, as the voice session uses it


def _pcm(duration_ms: int) -> int:
    return ms_to_bytes(duration_ms, RATE)


def _ledger(*chunks: tuple[str, int]) -> PlaybackLedger:
    """Build a ledger from (text, duration_ms) pairs."""
    ledger = PlaybackLedger(sample_rate=RATE)
    for text, duration_ms in chunks:
        ledger.add_chunk(text, _pcm(duration_ms))
    return ledger


def test_an_empty_ledger_has_heard_nothing() -> None:
    ledger = PlaybackLedger(sample_rate=RATE)
    assert ledger.spoken_prefix() == ""
    assert ledger.unspoken_remainder() == ""
    assert ledger.fully_played() is False


def test_nothing_played_means_nothing_heard() -> None:
    """The most dangerous case: audio was generated and sent, but never reached the speaker."""
    ledger = _ledger(("Maxwell's equations are four.", 1000))
    assert ledger.spoken_prefix() == ""
    assert ledger.unspoken_remainder() == "Maxwell's equations are four."


def test_fully_played_returns_the_whole_answer() -> None:
    ledger = _ledger(("First chunk. ", 500), ("Second chunk.", 500))
    ledger.acknowledge(1000)
    assert ledger.spoken_prefix() == "First chunk. Second chunk."
    assert ledger.unspoken_remainder() == ""
    assert ledger.fully_played() is True


def test_a_chunk_boundary_is_exact() -> None:
    ledger = _ledger(("AAAA", 500), ("BBBB", 500))
    ledger.acknowledge(500)
    assert ledger.spoken_prefix() == "AAAA"
    assert ledger.unspoken_remainder() == "BBBB"


def test_a_partially_played_chunk_is_interpolated_and_rounds_down() -> None:
    """Rounding down matters: history must never claim more was heard than was."""
    ledger = _ledger(("ABCDEFGHIJ", 1000))  # 10 chars over 1000 ms
    ledger.acknowledge(450)
    assert ledger.spoken_prefix() == "ABCD"  # 4.5 chars -> 4
    assert ledger.unspoken_remainder() == "EFGHIJ"


def test_playback_position_is_monotonic() -> None:
    """A reordered ACK must not rewind what we believe was heard."""
    ledger = _ledger(("ABCDEFGHIJ", 1000))
    ledger.acknowledge(800)
    ledger.acknowledge(200)  # arrives late, out of order
    assert ledger.played_ms == 800
    assert ledger.spoken_prefix() == "ABCDEFGH"


def test_an_ack_beyond_the_audio_is_clamped() -> None:
    """A buggy or hostile client cannot claim more was played than exists."""
    ledger = _ledger(("ABCD", 500))
    ledger.acknowledge(99_999)
    assert ledger.played_ms == 500
    assert ledger.spoken_prefix() == "ABCD"


def test_the_prefix_is_always_a_prefix_of_the_answer() -> None:
    """The invariant, checked across every playback position."""
    ledger = _ledger(("Kirchhoff's law. ", 900), ("The sum is zero. ", 900), ("Clear?", 400))
    full = ledger.text
    for position in range(0, ledger.total_audio_ms + 50, 25):
        prefix = ledger.spoken_prefix(position)
        assert full.startswith(prefix), (position, prefix)
        assert prefix + ledger.unspoken_remainder(position) == full


def test_the_prefix_never_shrinks_as_playback_advances() -> None:
    ledger = _ledger(("AAAAA", 500), ("BBBBB", 500))
    lengths = [len(ledger.spoken_prefix(p)) for p in range(0, 1001, 50)]
    assert lengths == sorted(lengths)


def test_a_silent_chunk_does_not_shift_later_offsets() -> None:
    """A chunk that produced no audio still gets an entry; skipping it would corrupt offsets."""
    ledger = PlaybackLedger(sample_rate=RATE)
    ledger.add_chunk("audible. ", _pcm(500))
    ledger.add_chunk("silent.", 0)
    ledger.add_chunk(" audible again.", _pcm(500))
    ledger.acknowledge(1000)
    assert ledger.spoken_prefix() == "audible. silent. audible again."


def test_durations_are_derived_from_audio_bytes_not_guessed() -> None:
    ledger = PlaybackLedger(sample_rate=RATE)
    entry = ledger.add_chunk("hello", _pcm(250))
    assert entry.duration_ms == 250
    assert ledger.total_audio_ms == 250


def test_character_offsets_are_contiguous() -> None:
    ledger = _ledger(("one ", 100), ("two ", 100), ("three", 100))
    assert [(e.char_start, e.char_end) for e in ledger.entries] == [(0, 4), (4, 8), (8, 13)]


def test_a_chunk_cancelled_mid_synthesis_is_still_in_the_record() -> None:
    """Found by an in-flight barge-in test.

    A chunk is registered when synthesis *starts*, not when it finishes. Otherwise a chunk that is
    still being synthesised when the student interrupts has its text recorded nowhere — neither as
    heard nor as unheard — which is the same defect class as storing the full generation.
    """
    ledger = PlaybackLedger(sample_rate=RATE)
    ledger.add_chunk("Fully synthesised. ", _pcm(500))
    ledger.begin_chunk("Half synthesised when cancelled.")
    ledger.extend_chunk(_pcm(100))  # only part of its audio was produced

    ledger.acknowledge(500)
    assert ledger.spoken_prefix() == "Fully synthesised. "
    # The interrupted chunk's text is accounted for, not silently dropped.
    assert ledger.unspoken_remainder() == "Half synthesised when cancelled."
    assert ledger.text.endswith("cancelled.")


def test_extending_grows_the_open_chunk_only() -> None:
    ledger = PlaybackLedger(sample_rate=RATE)
    ledger.add_chunk("first", _pcm(200))
    ledger.begin_chunk("second")
    ledger.extend_chunk(_pcm(50))
    ledger.extend_chunk(_pcm(50))

    assert ledger.entries[0].duration_ms == 200
    assert ledger.entries[1].duration_ms == 100
    assert ledger.total_audio_ms == 300


def test_extending_with_nothing_open_is_a_no_op() -> None:
    ledger = PlaybackLedger(sample_rate=RATE)
    ledger.extend_chunk(1000)
    assert ledger.total_audio_ms == 0


def test_durations_use_the_synthesised_audios_rate_not_the_capture_rate() -> None:
    """One second of 24 kHz speech is 48,000 bytes. Read at the 16 kHz capture rate it measures
    1.5 s, so a client that has played every sample still looks a third short: each barge-in
    under-records what was heard, and playback can never be seen to finish."""
    ledger = PlaybackLedger(sample_rate=24_000)
    ledger.add_chunk("one second of speech", 48_000)
    assert ledger.total_audio_ms == 1000
    ledger.acknowledge(1000)
    assert ledger.fully_played() is True
    assert ledger.spoken_prefix() == "one second of speech"
