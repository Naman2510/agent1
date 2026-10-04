# Datasets

**Empty.** No cases have been collected. Policy, versioning rules, the data-quality pipeline, and the
PII/legal position are in [`../docs/DATASET.md`](../docs/DATASET.md).

Layout once `v1` exists:

```
v1/
├── MANIFEST.yaml     # version, counts per language, provenance, licences, annotator agreement, known gaps
├── stt/              # cases.jsonl + audio/ (fixtures only — no personal voice data in git)
├── retrieval/        # queries.jsonl + relevance.jsonl
├── agent/            # scenarios.jsonl (expected tool traces)
├── response/         # cases.jsonl (question, context, rubric)
├── e2e/              # sessions.yaml (scripted multi-turn, incl. interruption offsets)
└── normalisation/    # norm-v1 rules used by the STT metrics
```

Two rules that matter more than the layout:

1. A version is **immutable** once any `evaluation_runs` row references it. Corrections create `v1.1`
   with a changelog entry; they never edit `v1`, because that would retroactively change published
   metrics.
2. **No personal data and no student voice recordings in this repository**, ever. `.gitignore` blocks
   audio formats except `datasets/**/fixtures/*.wav`, which holds only synthetic or explicitly
   released clips.
