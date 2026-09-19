# Sample corpus

**Self-authored for this project. Not real course material, not sourced from any textbook, and
not licensed content of any kind.** Written specifically to give the RAG pipeline something
realistic to ingest and to give the retrieval eval suite something to query against, in the same
subject area as the rest of this project's fixtures (EMT / circuit theory, matching the LID
dataset's domain).

Five short documents, deliberately covering topics whose retrieval difficulty differs — an easy
recall case, a case with genuine chunk-boundary ambiguity, a case requiring metadata filtering to
disambiguate two documents with overlapping vocabulary. See `datasets/v1/retrieval/cases.jsonl`
for the labelled queries against this corpus and `docs/adr/0006-embedding-model.md` for why the
embedder answering these queries is TF-IDF/SVD rather than the originally planned
`multilingual-e5-base`.

| File | Subject | Topic | Semester | Difficulty |
|---|---|---|---|---|
| `emt-01-kirchhoffs-laws.md` | Electromagnetic Theory | Kirchhoff's Laws | 3 | easy |
| `emt-02-maxwells-equations.md` | Electromagnetic Theory | Maxwell's Equations | 3 | medium |
| `emt-03-waveguides.md` | Electromagnetic Theory | Waveguides | 5 | hard |
| `ckt-01-network-theorems.md` | Circuit Theory | Network Theorems | 3 | medium |
| `ckt-02-transient-response.md` | Circuit Theory | Transient Response | 3 | medium |

No student data, no personal data, no third-party text. Licence: authored for this project, same
terms as the rest of the repository.
