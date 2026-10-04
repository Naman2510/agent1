"""The one Unicode-aware tokenizer shared by the lexical query builder, the TF-IDF embedder, and
the eval suite's offline BM25 comparison — previously duplicated in two of those three places,
which is how it could have drifted.

Uses `regex`, not the standard-library `re`: Python's built-in `\\w` matches Unicode letter and
number categories but not combining marks (category Mc/Mn), so a Devanagari or Tamil vowel sign —
a combining mark on its base consonant — breaks a word into fragments ("किरचॉफ" becomes "क", "रच",
"फ"). `\\p{L}\\p{M}\\p{N}` keeps a base letter and its combining marks together as one token
regardless of script. Found by running a real Hindi query against a real fit and seeing
single-character garbage tokens (Phase 5 audit).
"""

from __future__ import annotations

import regex

_WORD_PATTERN = regex.compile(r"[\p{L}\p{M}\p{N}]+")


def tokenize(text: str) -> list[str]:
    return _WORD_PATTERN.findall(text.casefold())
