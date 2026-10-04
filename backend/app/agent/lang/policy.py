"""What to do with a language decision: how to answer, and in which voice.

Three consequences flow from the routed language, and each has a failure that is audible rather
than silent:

* **The response directive.** Sent as a non-cacheable system block, so it can change per turn
  without invalidating the prompt cache (ARCHITECTURE §8.5).
* **Voice selection.** A Hindi answer in an English voice is intelligible but wrong; a Tamil
  answer in an English voice is close to unusable.
* **Transliteration.** Romanized Hindi handed to a multilingual voice tends to be read with
  English phonetics — "samjhao" as "sam-jow". The fix is to transliterate the Hindi spans to
  Devanagari before synthesis while leaving technical terms in Latin script. That is experiment
  EXP-006 and is **not implemented**: the decision point exists and returns a plan, and the
  transliterator behind it is a documented gap rather than a stub pretending to work (R-05).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.tts.base import Voice

# Which TTS language a routed language should be spoken in.
_VOICE_LANGUAGE = {
    "en": "en",
    "hi": "hi",
    "hi-Latn": "hi",  # romanized Hindi is still Hindi to a synthesiser
    "ta": "ta",
    "mixed": "hi",  # code-switched English/Hindi: the Hindi voice handles English better
    # than the reverse, though this is a judgement awaiting EXP-006
}

_DIRECTIVES = {
    "en": "The student is speaking English. Answer in English.",
    "hi": (
        "The student is speaking Hindi in Devanagari script. Answer in Hindi, in Devanagari. "
        "Keep standard technical terms in English — those are the words on their exam paper."
    ),
    "hi-Latn": (
        "The student is writing Hinglish: Hindi grammar in Latin script, with English technical "
        "terms. Answer the same way — Hindi in Latin script, technical terms in English. Do not "
        "switch them to Devanagari and do not answer in formal Hindi or formal English."
    ),
    "ta": (
        "The student is speaking Tamil. Answer in Tamil. Keep standard technical terms in English."
    ),
    "mixed": (
        "The student is mixing Hindi and English freely. Mirror that mix rather than picking one "
        "language; keep technical terms in English."
    ),
}


@dataclass(frozen=True)
class SpeechPlan:
    """How to synthesise this answer."""

    voice: Voice
    # True when the text should be transliterated to Devanagari before synthesis. The
    # transliterator does not exist yet (EXP-006), so this currently records intent — and the
    # session logs when it is set but cannot be honoured, rather than silently ignoring it.
    transliterate_to_devanagari: bool = False
    voice_matched_language: bool = True


def response_directive(language: str) -> str | None:
    """The per-turn instruction. None for an unrouted language, so nothing is asserted falsely."""
    return _DIRECTIVES.get(language)


def select_voice(language: str, voices: tuple[Voice, ...]) -> SpeechPlan:
    """Choose a voice, and say plainly when the choice is a compromise."""
    if not voices:  # pragma: no cover - a provider with no voices is a configuration error
        raise ValueError("the TTS provider offers no voices")

    wanted = _VOICE_LANGUAGE.get(language)
    if wanted is None:
        # A language the system does not route. Falling back to English is fine; reporting it as
        # a *match* is not — that would hide the gap from telemetry, which is the only place it
        # would ever be noticed.
        return SpeechPlan(
            voice=voices[0], transliterate_to_devanagari=False, voice_matched_language=False
        )

    for voice in voices:
        if voice.language == wanted:
            return SpeechPlan(
                voice=voice,
                # Romanized Hindi through an Indic voice is the case EXP-006 exists for.
                transliterate_to_devanagari=language in {"hi-Latn", "mixed"},
                voice_matched_language=True,
            )

    # No voice for this language. A wrong-accent answer beats silence, and the mismatch is
    # recorded so it shows up in telemetry instead of being discovered by a listener.
    return SpeechPlan(
        voice=voices[0], transliterate_to_devanagari=False, voice_matched_language=False
    )


def stored_language(language: str) -> str:
    """The value written to `messages.language`.

    Kept identical to the routed label rather than collapsed to a coarse language, because the
    per-language metrics in EVALUATION.md depend on telling `hi` from `hi-Latn` — they are the
    easy case and the hard case respectively.
    """
    return language
