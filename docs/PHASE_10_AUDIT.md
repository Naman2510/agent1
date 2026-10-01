# Phase 10 Audit — Audit Gate 10

**Reviewed:** the optional fine-tuning phase, meaning whether to fine-tune the intent classifier,
and the project's state at the end of its roadmap.
**Date:** 2026-09-30 · **Reviewer:** implementing engineer (self-audit).
**Method:** the classifier as built (`app/agent/intent.py`), what the evaluation suites measure
about it, its place in the latency budget and the price table, and the data rules it would need
(DATASET.md).

**Outcome:** a written decision not to fine-tune, [ADR-0017](adr/0017-intent-classifier-not-fine-tuned.md).
The prompted baseline the roadmap asks to compare against has never been measured: there is no
labelled set of real utterances and no run against a real model. EXP-010's preconditions, and
the rule that would justify a fine-tune, are now written down. No code changed in this phase.

**Gate status: PASSED.** The roadmap names "a written decision not to fine-tune" as a legitimate
outcome of this phase. This one rests on the absence of a measured baseline, not on a baseline
judged strong enough, and it says so.

---

## 1. Gate criterion

| Criterion | Evidence | Result |
|---|---|---|
| Zero-shot → prompted → fine-tuned on a held-out split, with cost and latency compared; or a written decision not to fine-tune | ADR-0017. **Prompted:** the gate exists, and only its structure is measured (allowlist coverage 14/14, the gate changing which calls run 5/5, injection 19/19, all under a scripted model). **Zero-shot and fine-tuned:** not run, because no labelled real utterances exist. **Cost:** estimated from the price table at about $1.20 per 1,000 turns on the default model, $0.24 on Haiku. **Latency:** unmeasured, and the call is on every turn's critical path against a 60 ms stage budget it cannot meet (M10-01) | pass: a written decision |

---

## 2. Findings

**M10-01 — The intent call and the latency budget disagree.** *Major.* ARCHITECTURE §9 budgets
60 ms for "STT final → language + intent". The gate is a model call that every answer waits for,
and a call to a hosted model does not fit 60 ms. The Phase 0 budget missed that the gate would be a
model call. *Scheduled:* the first real-model run (M9-01) measures the call, and ADR-0017's rule
takes it from there: a smaller tier first, then a local classifier only if the measurement asks
for one.

**m10-01 — A prompt too short to cache.** At about 220 tokens the classifier's prompt is below
the provider's minimum for caching, so every turn pays full input price for it. This is
negligible next to the answer's cost at these sizes, and recorded in ADR-0017.

No defects were found in this phase. It changed no code.

---

## 3. The project at the end of its roadmap

Phases 0 to 10 have passed their gates. What that does and does not mean, from the audits:

**Built, tested, and run in CI on every push:**
- A voice session over WebSocket with a server-side VAD, barge-in that keeps exactly what was
  heard, and a typed fallback. Also a typed chat path.
- Grounded answers with citations from hybrid retrieval, seven typed tools behind an intent gate,
  and two-tier memory.
- A web app with an admin dashboard.
- Recorded, reproducible evaluation: six suites, ten configs checked against baselines on every
  push and the recogniser's in tier T2, and three experiments decided under rules registered
  before they ran.
- Graceful degradation for every dependency, load measured on one process, and the security
  checklist reconciled item by item.
- 884 backend tests, 43 frontend unit tests, and 14 end-to-end tests against the Compose stack,
  32 runs across Chromium, Firefox and WebKit.

**Not true yet, and said so wherever it matters:**
- **No real provider in the loop.** The answers come from a scripted model and the voice from a
  fake synthesiser by default (a local one, eSpeak NG, now speaks them on request: ADR-0018), and
  the Claude adapter has never run against the live API. So there is no full-stack latency, and no
  measure of the mentor's own mistakes (M9-01, M8-01, M7-01).
- **Every dataset is self-authored or synthetic.** Nothing has been measured on a real student's
  voice or question (M9-02).
- **Two of the six planned evaluation suites** (`response`, `e2e`) do not exist (M9-03).
- **The recogniser's baselines are exact on one CPU model only** (AMD EPYC 7763), and compared,
  not enforced, on others. Two other models have differed, and its libraries promise no more
  (M9-04, FC-006).
- **Past about 50 connected voice students** the design is more processes, and that is not
  measured (M9-05).
- **Tamil** was deferred at the MVP decision and is not built.

The order in which these were left follows the project's rule: the pieces that can be measured
here are built and measured, and the ones that need a credential, a consented dataset or real
hardware are named, with what would unblock each.
