"""The shared Unicode-aware tokenizer.

This exists because Python's `\\w` silently drops Devanagari/Tamil combining marks (Phase 5
audit), fragmenting words at every vowel sign. These tests pin that behaviour down so it cannot
regress back to `re`-based tokenisation by accident.
"""

from __future__ import annotations

from app.rag.tokenize import tokenize


def test_devanagari_words_with_combining_marks_stay_whole() -> None:
    """The defect this module fixes: "किरचॉफ" contains combining vowel signs that a `\\w`-based
    regex drops, producing three character fragments instead of one word."""
    assert tokenize("किरचॉफ का नियम समझाओ") == ["किरचॉफ", "का", "नियम", "समझाओ"]


def test_tamil_words_with_combining_marks_stay_whole() -> None:
    assert tokenize("கிர்ச்சாஃப் விதியை") == ["கிர்ச்சாஃப்", "விதியை"]


def test_english_tokenizes_as_expected() -> None:
    assert tokenize("Kirchhoff's voltage law") == ["kirchhoff", "s", "voltage", "law"]


def test_casefolds() -> None:
    assert tokenize("KVL Kvl kvl") == ["kvl", "kvl", "kvl"]


def test_numbers_are_kept_as_tokens() -> None:
    assert tokenize("3.5 kilohms") == ["3", "5", "kilohms"]


def test_punctuation_and_whitespace_are_separators() -> None:
    assert tokenize("what,does; kvl?  state!") == ["what", "does", "kvl", "state"]


def test_empty_and_punctuation_only_input_tokenizes_to_nothing() -> None:
    assert tokenize("") == []
    assert tokenize("...!?") == []


def test_mixed_script_input_tokenizes_each_run_separately() -> None:
    """Code-switched text: 'displacement current' in Latin script inside a Devanagari sentence."""
    tokens = tokenize("displacement current का मतलब")
    assert "displacement" in tokens
    assert "current" in tokens
    assert "का" in tokens
    assert "मतलब" in tokens
