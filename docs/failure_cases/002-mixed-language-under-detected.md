# FC-002 — Genuinely code-switched utterances are classified as single-language

**Status:** open
**Found:** 2026-09-18 · **Phase:** 4 · **Component:** language routing
**Severity:** major
**Case IDs:** `mix-004`, `mix-006`, `mix-007` (dataset v1, LID slice)

## Input

```
"The derivation was fine lekin last step samajh nahi aaya"
"Yes bilkul that is what I meant to ask"
"If the flux changes to phir induced emf aayega na"
```

## Expected

`mixed` for all three — each has substantial English *and* Hindi grammatical structure, not just
English technical terms inside a Hindi sentence.

## Actual

`hi-Latn`, `en`, `hi-Latn`. Recall for the `mixed` class is **0.625** — the weakest row in the
report by a wide margin, against 1.00 for Devanagari Hindi and Tamil and 0.96 for romanized Hindi.

## Root cause

The `mixed` gate requires `evidence >= 4` tokens **and** both language shares `>= 0.25`. The three
cases fail it for two different reasons:

- `mix-004` (hi=2, en=1) and `mix-007` (hi=2, en=1): only 3 evidence tokens, below the gate. Much
  of each sentence is technical vocabulary, which is evidence for neither side by design.
- `mix-006` (hi=1, en=4): Hindi share is 0.20, under the 0.25 floor. A single Hindi discourse
  particle (`bilkul`) is genuinely weak evidence — but it is also exactly how code-switching
  presents.

So the gate is too strict, and it is too strict *because* the neutral-token rule that makes
romanized Hindi work so well removes the very evidence the `mixed` class needs.

## Proposed fix

Lower the evidence requirement to 3 and the share floor to 0.20, and measure the cost to `en` and
`hi-Latn` precision. The tension is real: loosening the gate will pull single-language utterances
containing one foreign particle into `mixed`.

## Decision

**Deliberately not tuned.** The obvious move — adjust two constants until the suite scores 100% —
would be fitting the classifier to a dataset written by the same person who wrote the classifier
(see the bias section of `datasets/v1/MANIFEST.yaml`). That produces a better number and a worse
system, and it is the specific failure this project's methodology exists to avoid.

The fix waits for either a second annotator on these 8 cases, or real student utterances. Recorded
as the leading candidate for the first genuine improvement once the dataset is trustworthy.

## Experiment

EXP-011 (registered, not designed): *lowering the `mixed` gate improves `mixed` recall without
reducing `en`/`hi-Latn` precision.* Baseline: `signal_macro_f1 0.8988`, `mixed` recall `0.625` on
dataset v1 at `0adf300`.

## Result

Not run. Blocked on a dataset that is not self-authored.
