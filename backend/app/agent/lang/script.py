"""Unicode script detection.

The cheapest and most reliable signal available: Devanagari and Tamil are settled by looking at
codepoints, with no model and no ambiguity. Spending anything cleverer on them would be waste.

What this cannot do is tell romanized Hindi from English — both are Latin script. That is the
whole of the hard problem (R-04) and it lives in `hinglish.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

DEVANAGARI = range(0x0900, 0x0980)
TAMIL = range(0x0B80, 0x0C00)
# Latin including the Latin-1 and Extended-A supplements, so accented characters count.
LATIN_MAX = 0x024F


class Script(StrEnum):
    LATIN = "latin"
    DEVANAGARI = "devanagari"
    TAMIL = "tamil"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScriptProfile:
    script: Script
    devanagari: int
    tamil: int
    latin: int
    # Share of alphabetic characters belonging to the dominant non-Latin script, if any.
    dominant_share: float

    @property
    def total(self) -> int:
        return self.devanagari + self.tamil + self.latin

    @property
    def is_latin_only(self) -> bool:
        return self.total > 0 and self.devanagari == 0 and self.tamil == 0


# A fifth of the alphabetic characters is enough: intra-sentence code-switching means a Hindi
# question can be mostly Latin technical terms and still be a Hindi question. The threshold is
# part of the metric definition in DATASET.md, not a free parameter.
NON_LATIN_THRESHOLD = 0.2


def profile(text: str) -> ScriptProfile:
    devanagari = tamil = latin = 0
    for char in text:
        if not char.isalpha():
            continue
        code = ord(char)
        if code in DEVANAGARI:
            devanagari += 1
        elif code in TAMIL:
            tamil += 1
        elif code <= LATIN_MAX:
            latin += 1

    total = devanagari + tamil + latin
    if total == 0:
        return ScriptProfile(Script.UNKNOWN, 0, 0, 0, 0.0)

    deva_share = devanagari / total
    tamil_share = tamil / total

    if deva_share >= NON_LATIN_THRESHOLD and tamil_share >= NON_LATIN_THRESHOLD:
        return ScriptProfile(Script.MIXED, devanagari, tamil, latin, max(deva_share, tamil_share))
    if deva_share >= NON_LATIN_THRESHOLD:
        return ScriptProfile(Script.DEVANAGARI, devanagari, tamil, latin, deva_share)
    if tamil_share >= NON_LATIN_THRESHOLD:
        return ScriptProfile(Script.TAMIL, devanagari, tamil, latin, tamil_share)
    if latin:
        return ScriptProfile(Script.LATIN, devanagari, tamil, latin, latin / total)
    return ScriptProfile(Script.UNKNOWN, devanagari, tamil, latin, 0.0)
