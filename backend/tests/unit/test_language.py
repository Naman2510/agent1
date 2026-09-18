"""The Phase 2 script signal. Not the language router — that is Phase 4 (ADR-0011)."""

import pytest

from app.agent.language import script_of


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Explain Kirchhoff's voltage law", "en"),
        ("Kirchhoff ka voltage law samjhao", "en"),  # romanized Hindi: Latin script
        ("किरचॉफ का वोल्टेज नियम समझाओ", "hi"),
        ("கிர்ச்சாஃப் விதியை விளக்குங்கள்", "ta"),
        ("KVL का मतलब क्या है", "hi"),  # mixed script, Devanagari above threshold
        ("3.5 kΩ", "en"),
        ("", "unknown"),
        ("42 + 7 = 49", "unknown"),
    ],
)
def test_script_detection(text: str, expected: str) -> None:
    assert script_of(text) == expected


def test_romanized_hindi_is_indistinguishable_from_english_here() -> None:
    """The documented limitation, asserted so nobody mistakes this for a language detector.

    Both are Latin script, so both come back 'en'. Telling them apart is the open problem in
    ADR-0011 and the subject of R-04 — it is not solved by this function and must not be assumed.
    """
    assert script_of("Bhai KVL basically kya bol raha hai") == script_of(
        "What does KVL actually mean"
    )
