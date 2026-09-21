# Datasets

**Status:** Phase 6. Three of the six slices in `datasets/v1/` are real: `lid` (88 cases, Phase 4),
`retrieval` (22 cases, Phase 5), and `agent`, partially — 16 prompt-injection cases
(`injection_cases.jsonl`) exist; the expected-tool-trace cases (`scenarios.jsonl`, §1's original
plan for this directory) are separate and may not exist yet, see the `agent` slice entry below for
current status. The rest — `stt`, `response`, `e2e` — do not exist yet; the layout in §1 is the
target, not a claim that every directory is populated.

---

## 1. Versioning

```
datasets/
├── v1/
│   ├── MANIFEST.yaml          # version, created, counts, provenance, licence, changelog
│   ├── stt/                   #   cases.jsonl + audio/ (fixtures only; see §5)
│   ├── retrieval/             #   queries.jsonl + relevance.jsonl
│   ├── agent/                 #   scenarios.jsonl (expected tool traces);
│   │                          #   injection_cases.jsonl (prompt-injection defense, Phase 6)
│   ├── response/              #   cases.jsonl (question, context, rubric)
│   ├── e2e/                   #   sessions.yaml (scripted multi-turn, incl. interruptions)
│   └── normalisation/         #   norm-v1 rules used by STT metrics
└── v2/ …
```

A dataset version is **immutable once a run references it**. Fixing a bad label creates `v1.1` with a
changelog entry; it never edits `v1`, because that would retroactively change published metrics.
`MANIFEST.yaml` records: case counts per language, how each case was sourced, annotator count and
agreement, licence for every third-party asset, and known gaps.

## 2. Coverage targets (v1)

Targets, not achievements. Numbers are deliberate minimums for a first useful set, not a claim of
statistical power — with ~50 cases per language a WER difference under a few points is noise, and the
manifest says so.

| Slice | Target cases | Notes |
|---|---|---|
| English | 60 | technical vocabulary, formulae, numerals |
| Hindi (Devanagari) | 50 | natural student phrasing, not translated English |
| Hinglish (romanized, code-switched) | 60 | the priority slice — this is the project's hard case |
| Tamil | 50 | natural Tamil student queries |
| Intra-utterance code-switch | 25 | language switches mid-sentence |
| Indian names | 25 | pronunciation and transcription of names |
| Numbers / units / formulae | 25 | "3.5 kΩ", "10 to the power minus 9" |
| Noisy audio | 25 | fan, traffic, hostel room; SNR labelled |
| Interruptions | 20 | barge-in at labelled offsets (e2e) |
| Ambiguous questions | 15 | should trigger a clarifying question, not a guess |
| RAG-answerable | 40 | with labelled relevant chunks |
| Tool-requiring | 40 | with expected tool traces |
| Hallucination traps | 25 | plausible-but-absent facts; correct answer is "I don't know" |
| Out-of-scope / unsafe | 15 | refusal and redirection behaviour |
| Prompt-injection | 15 | injected instructions in documents and in speech |

## 3. Sourcing, honestly

Three sources, each with different validity:

1. **Self-recorded** (developer + consenting volunteers) — the only source for voice audio in v1.
   Small, and accent coverage is narrow. This is the dominant limitation of the STT numbers and the
   manifest states it in those words.
2. **Public corpora** — used only where the licence permits and is recorded per asset (e.g.
   Common Voice, AI4Bharat/IndicVoices-family releases, under their own terms). Each asset's licence
   goes in `MANIFEST.yaml`; anything unclear is not used.
3. **Synthetic** — TTS-generated audio and LLM-generated text cases, **always labelled
   `synthetic: true`** and reported separately. Synthetic audio systematically understates ASR
   difficulty (clean, no disfluency, no room acoustics), so a WER measured on it is not comparable to
   a WER measured on human speech. Mixing them into one aggregate would be a fabricated result.

Text cases (retrieval, agent, response) may be authored directly; the author is recorded, and cases
authored by the same person who wrote the prompt under test are flagged, because that is a bias.

## 4. Data-quality pipeline

```
raw submission
   → schema validation (pydantic; rejects on missing fields, bad audio format)
   → audio checks (sample rate, clipping, duration bounds, SNR estimate)
   → language identification (recorded as a label, and compared against the human label)
   → normalisation (Unicode NFC, whitespace, numeral policy — norm-v1)
   → PII detection & redaction (see §5)
   → quality filtering (unusable audio, empty or duplicate references)
   → annotation (transcript / relevance / expected tool trace)
   → inter-annotator agreement on a ≥20% overlap sample
   → split (eval-only in v1; no training split until fine-tuning is justified)
   → version + manifest + immutable tag
```

Every rejection is logged with a reason, so the drop rate is visible rather than silent.

## 5. PII and legal position

This project handles voice recordings of students in India, some of whom may be minors. That is
regulated personal data under the **Digital Personal Data Protection Act, 2023**, which requires
purpose-limited consent and verifiable parental consent for children. Concretely:

- **No personal data, and no student voice recordings, are committed to this repository.** The
  `.gitignore` blocks audio formats; the only committed audio is a handful of synthetic or
  explicitly-released fixtures under `datasets/**/fixtures/`.
- Voice data lives outside git, with the storage location and access controls documented in
  [SECURITY.md](SECURITY.md).
- Audio retention is **opt-in per student** (`students.consent_audio_retention`, default `false`).
  Without consent, audio exists only in memory for the duration of the turn.
- Transcripts are PII-scanned (names, phone numbers, emails, roll numbers) and redacted before
  entering any dataset. Names that are *the point of a case* (Indian-name recognition) use
  volunteer-consented or public-figure names, recorded as such.
- Deletion is real: `ON DELETE CASCADE` from `students` plus a documented procedure for removing a
  student's rows from dataset versions (which invalidates affected runs — noted in the manifest
  rather than hidden).
- Third-party providers process audio and transcripts. Which provider sees what is listed in
  [SECURITY.md](SECURITY.md#5-data-handling), and consent language must name it.

This is a student project, not a law firm's opinion — but "we did not think about it" is not an
acceptable answer for a system that records people's voices, so the position is written down and can
be corrected.

## 6. What v1 will not support

- Broad accent coverage across Indian English varieties.
- Statistically powered comparisons — sample sizes support direction, not tight confidence intervals.
- Dialectal Hindi or Tamil variation.
- Any training split. Fine-tuning data is created only if EXP-010 is justified, as a separate
  versioned dataset with its own labelling protocol.
