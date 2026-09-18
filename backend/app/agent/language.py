"""Minimal language signal for the Phase 2 text path.

This is **not** the language router from ADR-0011. That needs script detection with hysteresis, a
romanized-Hinglish classifier and session-sticky state, and it lands in Phase 4 with the metrics
to judge it by. What exists here is the one signal that is genuinely free — Unicode script — used
only to tag stored messages, so Phase 4 has real data to compare against.
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
