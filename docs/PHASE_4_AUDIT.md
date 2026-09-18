# Phase 4 Audit — Audit Gate 4

**Reviewed:** language routing — script detection, the romanized-Hinglish classifier, sticky
session state with hysteresis, the response-language policy and voice selection — plus the first
working evaluation suite and the first versioned dataset.
**Date:** 2026-09-18 · **Reviewer:** implementing engineer (self-audit).
**Method:** the eight Gate dimensions plus the Phase 4 gate criteria, each checked by running
something. 423 tests, 96% coverage, `ruff`, `ruff format` and `mypy` clean.

**Outcome:** 2 defects found and fixed, 5 Major items scheduled, 4 Minor recorded. One deliberate
decision *not* to improve a number.

**Gate status: PASSED.**

---

## 1. Gate criteria

| Criterion | Evidence | Result |
|---|---|---|
| Per-language LID accuracy recorded as a baseline | `python -m eval.runner --suite lid --dataset v1`: signal accuracy **0.9205**, macro F1 **0.8988**; routed accuracy 0.8750. Full per-language and per-difficulty breakdown in [EVALUATION.md §2a](EVALUATION.md). Reproducible from a committed dataset with a recorded git SHA | pass |
| Mid-conversation switching preserves context | `test_mid_conversation_language_switching_preserves_context` runs four turns across English → Hinglish → Devanagari and asserts the English opening turn is still in the final prompt, with per-turn language tags `["en", "hi-Latn", "hi-Latn", "hi"]` | pass |

Also verified: the cacheable prompt prefix is byte-identical across a language switch while the
per-turn directive differs (so routing cannot invalidate the prompt cache); the selected TTS voice
follows the routed language; and a language with no voice reports the mismatch rather than
claiming a match.

---

## 2. Defects found and fixed

### D4-01 — "Tamil" written in Devanagari routed to Hindi
**Severity: medium.** The explicit-request table had `तमिल` (the Devanagari spelling of "Tamil")
inside the *Hindi* alternation, so `"तमिल में बताओ"` — a request **for Tamil** — set the session
language to Hindi and locked it there. A copy-paste in a regex table, invisible on reading, and
the kind of thing that only shows up if you test the case.

**Fix:** separate patterns for `तमिल` → `ta`, plus Tamil-script requests for Tamil and English.
Caught by a parametrised test over the request table.

### D4-02 — An unrouted language reported a *matched* voice
**Severity: low, but it defeated the telemetry.** `select_voice` used
`_VOICE_LANGUAGE.get(language, "en")`, so Malayalam resolved to `"en"`, found an English voice, and
returned `voice_matched_language=True`. The fallback was correct; reporting it as a match hid the
gap from the only place anyone would notice it.

**Fix:** an unmapped language returns the fallback with `voice_matched_language=False` and logs a
warning. The distinction between "we speak this language" and "we gave up and used English" is
now visible.

---

## 3. A deliberate decision not to improve a number

`mixed` recall is **0.625** — the weakest row in the report. The cause is precise and the fix is
obvious: the gate requires 4 evidence tokens and a 0.25 share on both sides, and the three failing
cases miss by one token or 0.05 of share. Lowering two constants would very likely score 1.000 on
this dataset.

**Not done.** The 88 cases were written by the same person who wrote the lexicon, so tuning against
them is fitting a classifier to its own author — a better number and a worse system, and precisely
the failure mode this project's methodology exists to prevent. It is registered as EXP-011, blocked
on a dataset that is not self-authored, and written up as
[FC-002](failure_cases/002-mixed-language-under-detected.md).

This is recorded here because "we declined to optimise" is a result, and because the temptation was
real and immediate.

---

## 4. Major findings (scheduled)

**M4-01 — The LID baseline measures internal consistency, not accuracy.**
Single annotator, cases authored by the author of the lexicon, no inter-annotator agreement. The
bias is documented at severity `high` in `datasets/v1/MANIFEST.yaml`, in the suite's docstring, in
the runner's output, and in EVALUATION.md — four places, because a number this quotable will
otherwise be quoted without its caveat. *Blocking for:* any claim about real-world LID accuracy.
*Scheduled:* a second annotator on the `mixed` slice, then real student utterances.

**M4-02 — Romanized Hindi at 0.960 is the least trustworthy figure in the report.**
It is simultaneously the project's flagship hard case (R-04) and the most bias-exposed number,
because the lexicon and the cases were written together. Treat it as an upper bound.

**M4-03 — Transliteration for code-switched TTS does not exist.**
`SpeechPlan.transliterate_to_devanagari` is computed, logged, and then ignored — romanized Hindi
still goes to the synthesiser as Latin text, which a multilingual voice reads with English
phonetics (R-05). The decision point exists so the gap is explicit rather than forgotten; the
transliterator is EXP-006. *Scheduled* with a real TTS provider, since the need depends on which
provider is chosen.

**M4-04 — The ASR language hint is collected and unused.**
`FinalTranscript.language_hint` is stored on the transcript but deliberately does not feed the
decision, because providers label romanized Hindi as English. That is the right call today, and it
also means a genuinely good provider hint would be wasted. *Scheduled Phase 8:* measure the hint's
accuracy against the LID labels and fold it in as a weighted signal if it earns a place.

**M4-05 — Tamil is recognised but unevaluated.**
Devanagari-script and Tamil-script detection are perfect by construction, but romanized Tamil has
two cases and a confidence cap of 0.5, and Tamil is deferred past the MVP (Gate 0 M-01). The
router will not mistake Tamil for English; beyond that, nothing is claimed.

---

## 5. Minor findings

| ID | Finding | Disposition |
|---|---|---|
| m4-01 | Three tokens (`me`, `to`, `the`) are valid in both languages and count as evidence for neither | Correct, and asserted by a test so the lexicons cannot drift back into overlapping |
| m4-02 | The hysteresis costs one turn of lag when following a genuine switch | Accepted and documented: the alternative is switching language because someone said "ok". The mentor still *answers* in the new language immediately; only the prior lags |
| m4-03 | `unknown` scores zero recall in the routed report | A metric artifact — the router must pick a language, because a voice product has to answer in one. Explained in EVALUATION.md rather than hidden |
| m4-04 | The lexicon is hand-curated, not corpus-derived or frequency-weighted | Stated in the module docstring. A frequency-weighted list needs a corpus, which needs the dataset work in M4-01 |

---

## 6. Dimensions reviewed with no finding above Minor

**Architecture consistency.** ADR-0011's layered policy is implemented as specified — explicit
request, then script, then classifier, then sticky prior — and the two properties the ADR argued
for both hold in tests: mid-conversation switching works, and context is never partitioned by
language. The router is a pure function over `(text, state)`, so the session owns storage and the
whole policy is testable without Redis.

**Unnecessary complexity.** No model was added. Script detection settles Devanagari and Tamil for
free, and the hard case gets a lexicon whose every decision is traceable to the tokens that caused
it — which is why all seven failures above could be diagnosed in one pass. A trained classifier
would have produced a similar number and no explanations.

**Testing strategy.** Conversation behaviour is tested as *sequences*, because stickiness and
hysteresis only exist across turns; the per-utterance signal is measured by the eval suite instead.
The suite's own arithmetic is tested too — an evaluation harness that silently miscounts is worse
than none — including a test that the dataset contains cases the system is expected to fail, since
a set of only easy cases produces a flattering number and no information.

**Evaluation strategy.** This phase turned the framework from a document into something that runs:
a versioned dataset with a manifest, a suite, per-class and per-difficulty metrics, a recorded
baseline asserted as a floor by a test, and two failure cases with root causes. The CI T1 tier now
runs it on every push at zero cost.

---

## 7. Gate decision

**PASSED.** Phase 5 (RAG) may begin.

Carried forward, unchanged in priority from Gate 3:
1. Run `scripts/smoke_llm.py` with a credential — the Claude adapter is still unexercised live.
2. Choose and implement a real ASR and TTS adapter; then measure TTFA.
3. Collect real speech: it unblocks VAD tuning (M3-04), the LID bias (M4-01), and the `mixed`
   experiment (EXP-011) simultaneously. This is now the single highest-value non-code task in the
   project.
