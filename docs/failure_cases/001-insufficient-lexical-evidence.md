# FC-001 — Short English utterances carry no language signal

**Status:** accepted-limitation
**Found:** 2026-09-18 · **Phase:** 4 · **Component:** language routing
**Severity:** minor
**Case IDs:** `en-001`, `en-010`, `en-017`, `hil-006` (dataset v1, LID slice)

## Input

```
"Explain Kirchhoff's voltage law to me"
"Is the answer three point five kilohms"
"Actually never mind continue"
"Maxwell equations pe paanch sawal do"
```

## Expected

`en`, `en`, `en`, `hi-Latn`.

## Actual

All four produce **no usable language signal**, so the router falls back to the session's sticky
prior. In the LID suite's strict `signal` report they count as `unknown` (4 of the 7 failures at
92.05% accuracy).

## Root cause

The lexicon counts *grammatical scaffolding* and deliberately ignores two token classes:
technical vocabulary (`voltage`, `law`, `maxwell`, `equations`) because a Hindi sentence keeps
those in English on purpose, and words valid in both languages (`to`, `me`, `the`).

That leaves these utterances with one evidence token each — `explain`, `is`, `actually`, `pe` —
and one token is below `MIN_EVIDENCE_TOKENS`, so confidence is capped at 0.3, under the 0.4
`ROMANIZED_TRUST` bar.

Note what the *system* did, as distinct from the classifier: three of the four were answered in
the correct language anyway, because the sticky prior was already right. The failure is in the
signal, not in the outcome — which is exactly why the suite reports both numbers.

## Proposed fix

Options, in increasing cost:

1. **Nothing.** The sticky prior handles this correctly in a real conversation, and the first
   utterance of a session defaults to English, which is the right default for this audience. The
   only true failure is `hil-006` — a Hinglish opener misread as English.
2. Add English content-word coverage so `explain`/`continue`/`answer` carry more weight. Cheap,
   but it makes the lexicon a general English dictionary, and every addition risks the reverse
   error on Hinglish sentences containing English content words.
3. Use character n-grams rather than a word list. Handles unseen spellings, loses the legibility
   that makes these failures diagnosable at all.
4. Fine-tune a small classifier (EXP-010).

## Decision

**Accepted as a limitation for now.** Option 1: the behaviour is correct in conversation, and the
cost of options 2–4 is not justified by a failure mode that the sticky prior already absorbs.
Revisit when real utterances show first-turn misrouting actually happening.

## Result

Not measured — no change was made. The baseline it would be compared against is
`signal_accuracy 0.9205` on dataset v1 at `0adf300`.
