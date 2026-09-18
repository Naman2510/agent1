"""Coarse script signal, retained for the text path and for telemetry.

Superseded as a *decision* by `app.agent.lang.router`, which adds the romanized-Hinglish
classifier and sticky session state (ADR-0011). This function remains because a cheap script tag
is still useful where no session state exists, and because its documented limitation — romanized
Hindi is indistinguishable from English here — is asserted by a test that would otherwise have
nowhere to live.
"""

from __future__ import annotations

DEVANAGARI = range(0x0900, 0x0980)
TAMIL = range(0x0B80, 0x0C00)


def script_of(text: str) -> str:
    """Classify by dominant script. Returns 'hi', 'ta', 'en', or 'unknown'.

    A Latin-script result is reported as 'en' *provisionally*: romanized Hindi is Latin script too,
    and telling them apart is the open problem in ADR-0011 (R-04). Callers must not treat 'en'
    from this function as a confident answer.
    """
    devanagari = tamil = latin = 0
    for char in text:
        code = ord(char)
        if code in DEVANAGARI:
            devanagari += 1
        elif code in TAMIL:
            tamil += 1
        elif char.isalpha() and code < 0x0250:
            latin += 1

    total = devanagari + tamil + latin
    if total == 0:
        return "unknown"
    if devanagari / total >= 0.2:
        return "hi"
    if tamil / total >= 0.2:
        return "ta"
    if latin:
        return "en"
    return "unknown"
