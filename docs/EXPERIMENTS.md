# Experiments

Each experiment here was registered — hypothesis, the one variable, the decision rule with its
guards, and a written prediction — in `backend/eval/experiments/` and committed *before* either run,
so no threshold was chosen after the numbers were known (EVALUATION.md §7). Both runs are recorded
(`evaluation_runs`, with every case in `evaluation_results`, and in MLflow), the decision is stored
in `experiments`, and any run reproduces from its record:

```
python -m eval.runner --experiment eval/experiments/EXP-003.toml --record
python -m eval.runner --reproduce <evaluation_runs id>
```

The decision rule (`backend/eval/decision.py`) compares the two runs case by case, with a seeded
bootstrap (10 000 resamples) of the mean per-case gain: **adopt** at a gain of at least the
registered effect with the 95% interval above zero and no guard failed; **reject** at the mirror
image, or if any guard fails; **inconclusive** otherwise.

| ID | Question | Decision |
|---|---|---|
| [EXP-003](#exp-003--semantic-endpointing-rejected) | Does ending the turn early on a complete-looking transcript cut latency without cutting students off? | **rejected** |
| [EXP-008](#exp-008--heading-path-prefixing-inconclusive) | Does prefixing chunks with their heading path improve ranking? | **inconclusive** |
| [EXP-013](#exp-013--the-routed-language-as-the-recognisers-language-inconclusive) | Does telling the recogniser the routed language beat letting it detect one? | **inconclusive** |
| [EXP-001](#exp-001--managed-indic-asr-vs-local-faster-whisper-blocked) | Does a managed Indic ASR beat local faster-whisper on Hinglish? | blocked |
| [EXP-007](#exp-007--hybrid-vs-vector-only-on-hindi-and-tamil-queries-blocked) | Does hybrid retrieval beat vector-only on Hindi/Tamil queries? | blocked |
| [EXP-012](#exp-012--semantic-endpointing-only-on-a-question-registered) | Does requiring a question, not just a sentence end, keep EXP-003's gain without the cut-offs? | registered |

---

## EXP-003 — Semantic endpointing: rejected

**Hypothesis.** Ending the turn after 250 ms of pause, when the stable transcript already reads as a
complete sentence, cuts turn-end latency by at least 100 ms without cutting off more questions.

**Variable.** `session.semantic_endpointing`, off → on. Everything else is the production
configuration (`voice.toml`; a test holds it to the application's defaults). The candidate is the
shallow rule ARCHITECTURE §4.3 describes: terminal punctuation on a stable prefix of at least eight
characters.

**Rule.** Adopt if turn-end time (speech end → turn, per question) falls by ≥ 100 ms with the
interval below zero; guards: no increase at all in questions cut off mid-turn, or in questions
missed.

**Prediction** (committed with the rule): faster on every final pause, but a turn that opens with a
complete sentence is cut at any pause the transcript completes in — so the cut-off guard should
fail, and the rule reject.

**Runs.** Suite `voice`, dataset v1 (sha256 `a90a7fde01cb…`), git `33314a9`, clean tree.
Baseline `429e29bd-ce7c-42b9-bbaf-ae6a62c2484f`, candidate `e417f75c-7284-4cfc-99ce-e25f07a899c8`.
Both reproduce exactly from their records, and CI re-runs both configs against their committed
baselines on every push.

| | Baseline (gate only) | Candidate (semantic) |
|---|---|---|
| Turn end, mean / p50 / p90 | 575 / 570 / 640 ms | **348 / 340 / 380 ms** |
| Question heard, mean | 298 ms | 298 ms |
| Questions cut off mid-turn | 9 of 36 | **12 of 36** |
| — one sentence (12) | 0 | 0 |
| — hesitation mid-sentence (12) | 4 | 4 |
| — two sentences (12) | 5 | **8** |
| Missed / false turns | 0 / 0 | 0 / 0 |

**Decision: reject.** The latency win clears its bar many times over — +227 ms mean
(95% CI [+217, +237]), faster on all 36 questions — and the cut-off guard fails: three more
questions cut off (+8.3 points).

**Which three.** `multi-en-04` "Let me see. … Is the answer twelve volts?" (400 ms pause),
`multi-en-05` "That makes sense. … Can you give me another example?" (450 ms), and `multi-hil-02`
"Theek hai. … Ab Thevenin theorem samjhao." (400 ms). Each opens with a complete statement; the
transcript completed 300 ms into the pause, with 250 ms of quiet counted, and the detector ended
the turn while the student was about to ask the actual question. Two-sentence turns with pauses of
250–350 ms escaped only because the student spoke again before the transcript completed. A
hesitation mid-sentence was never cut early — it has no closing punctuation — which is the half of
the design that works.

**Prediction against result.** Right about the decision and the reason. I expected cut-offs from
about 300 ms of pause; they began at 400 ms, because the gate starts counting a pause only once
Silero's probability has fallen below the exit threshold, a few windows after the speech stops.

**What it means.** Terminal punctuation marks the end of a sentence, not of a turn. The rule is not
wrong about how much time there is to win — more than a fifth of a second on every question — but
it spends that on cutting in on students who open with a sentence before asking. The switch stays
off, as it always was.

**What the result depends on,** each of which could move it:
- *The recogniser's lag.* The stand-in releases each word 300 ms after it is spoken. A slower
  recogniser shrinks the gain and pushes the cut-off threshold to longer pauses; a faster one does
  the reverse. No real recogniser has been measured (M7-01).
- *The mix of turns.* One question in three opens with a separate sentence, by construction. How
  often real students do that is unknown — and at a guard of zero, even a small share rejects.
- *Synthetic speech.* eSpeak's silences are cleaner than a room's; real pauses are noisier, and
  Silero's fall-off after real speech may differ.

**Next.** EXP-012 below: the same early end, but only on a question.

## EXP-008 — Heading-path prefixing: inconclusive

**Hypothesis.** Prefixing each chunk's embedded text with its document title and heading path
raises nDCG@10 on the retrieval set by at least 0.02.

**Variable.** `embedding.heading_prefix`, off → on (the candidate is what has shipped since
Phase 5). Guard: recall@10 may not fall.

**Prediction:** a small gain, too small to separate from noise on 22 queries: inconclusive.

**Runs.** Suite `retrieval`, dataset v1 (retrieval files sha256 `73d2058fee4f…`), git `33314a9`.
Baseline `89aa12f2-6af9-4fcf-9ac6-f04b1ba7b0db`, candidate `e7e523b9-870c-4dd4-b533-401a274c6f82`.

| | No prefix | Prefix (shipped) |
|---|---|---|
| nDCG@10 | 0.875 | 0.893 |
| MRR | 0.849 | 0.871 |
| Recall@5 | 0.955 | 0.932 |
| Recall@10 | 0.955 | 0.955 |

**Decision: inconclusive.** Mean gain +0.018 (95% CI [−0.002, +0.053]): below the registered
0.02, and the interval reaches zero. Nineteen of 22 queries are unchanged. The three that moved:
`ret-018` "TE and TM mode difference" 0.63 → 1.00 (the heading carries the query's own terms),
`ret-016` "KVL" 0.65 → 0.69, and `ret-001` "What does KVL state?" 0.54 → 0.52 — which also lost a
relevant chunk from its top five, the whole of the recall@5 drop.

**What it means.** On 19 self-authored chunks this set cannot resolve an effect of this size. The
prefix stays, as shipped, but without a claim that it helps: the record now says "not shown either
way", which is what the evidence supports. A corpus of real lecture material with headings written
by someone else would be the fair test.

## EXP-013 — The routed language as the recogniser's language: inconclusive

**Hypothesis.** Telling the recogniser each utterance's language — as the session's router has
already decided it (ADR-0011) — instead of letting Whisper detect it, cuts word error rate by at
least 0.1 without making English worse.

**Variable.** `recogniser.language`, `auto` → `hint` (the case's own label: `en` for English and
for romanized Hindi, which Whisper writes in Latin script only when told English; `hi` for
Devanagari). An upper bound: a real router can be wrong on a session's first utterance.

**Rule.** Adopt if per-case WER falls by at least 0.1 with the interval below zero; guard: English
WER may not rise at all (`wer_en`, maximum loss 0).

**Prediction** (committed with the rule, bdcad75): Hindi improves, "but by how much is the open
question, since eSpeak's Hindi may be too poor for Whisper to transcribe even when told what it
is"; English does not move; romanized Hindi barely moves.

**Runs.** Suite `stt`, dataset v1 (sha256 `1084397f02d7…`), faster-whisper `small` int8, beam 5,
seeded, arithmetic pinned (FC-006), CI tier T2 at f94fccd on an AMD EPYC 7763. Both runs are held to
committed baselines (`stt.json`, `stt-language-hint.json`); the candidate's reproduced exactly the
baseline an earlier run had written on another machine. T2 has no database, so neither run is in
`evaluation_runs`: the record is the baselines and the run's log.

| | Auto-detected | Told the routed language |
|---|---|---|
| WER, pooled — all / English / Hindi / romanized | 0.447 / 0.123 / 1.425 / 0.941 | **0.377** / 0.123 / **0.957** / 0.941 |
| CER — Hindi | 1.198 | 0.633 |
| Language detected as written — Hindi | 0 of 11 | 11 of 11 |
| Word for word — all | 30 of 66 | 30 of 66 |

**Decision: inconclusive.** Per-case WER 0.489 → 0.416: a mean gain of +0.073 (95% CI [+0.027,
+0.127]), 8 cases better and none worse — a real improvement, below the registered 0.1. The guard
held: every English case came back word for word the same, as did every romanized one. All eight
gains are Hindi; the other three Hindi cases stayed at WER 1.

**Prediction against result.** Right on every direction, and on the open question: told it is
Hindi, `small` writes Devanagari, and phonetically close — `इस सर्किट में` → `इस्टागिट में`, `अब अगला
उदाहरण बताइए।` → `अब आब लव बादव बबाई` — but still wrong nearly word for word. The auto-detected
Hindi is gone: no more `It's a cock-a-doodle-doo.` for `किरचॉफ का करंट नियम`.

**What it means.** Detection was the first failure, and the hint removes it; the acoustics are the
second, and nothing here changes them. The rule averaged over all 66 cases, of which Hindi is 11,
so an all-case gain of 0.1 needed Hindi to improve by about 0.6 per case; it improved by about 0.44.
That was a registration choice, made before the result and kept after it: the verdict stands. Not
adopted as a change — and nothing to adopt yet in the product, whose local recogniser is for
evaluation and whose real-time recogniser (ADR-0002) does not exist.

**Next.** The fair test is a recogniser that has heard Hindi (EXP-001) on Hindi a person spoke —
both blocked on data this project does not have (DATASET.md).

## EXP-001 — Managed Indic ASR vs local faster-whisper: blocked

Not run; nothing is concluded. The `stt` suite and the local model it compares against now exist
(CI tier T2), but it needs two things that do not: human speech with reference transcripts (none
consented yet, DATASET.md) and a managed ASR credential.

## EXP-007 — Hybrid vs vector-only on Hindi and Tamil queries: blocked

Not run as an experiment, because the data cannot answer it: the retrieval set has two Hindi
queries and no Tamil. The recorded runs already show hybrid and vector-only identical on both (one
found, one not: 0.500 on every metric). Two cases cannot size a difference; this needs a
multilingual query set written by someone other than the pipeline's author (DATASET.md).

## EXP-012 — Semantic endpointing only on a question: registered

**Hypothesis.** Ending early only when the stable transcript ends in a question — not merely a
sentence — keeps most of EXP-003's latency gain without its cut-offs.

Suggested by EXP-003's failures, all three of which opened with a statement. **That is exactly why
it cannot be tested on the dataset that suggested it**: a rule fitted to these twelve two-sentence
turns would pass them by construction. It waits for fresh cases — ideally human, and at least
written without looking at these results — and for a completeness test that also handles
questions without a question mark ("Explain the superposition theorem.").
