# FC-013 — An embedding outage turned every source-seeking answer into an apology

**Status:** fixed
**Found:** 2026-09-27 · **Phase:** 9 · **Component:** rag / agent tools
**Severity:** major
**Case IDs:** `test_embeddings_down_an_answer_still_finds_and_cites_its_source`;
`test_embeddings_down_retrieval_falls_back_to_the_lexical_arm`;
`test_tool_executor.py::test_a_tool_whose_provider_is_down_is_an_error_the_model_can_answer_around`

## Input

"What is KVL?" in a session whose course material includes a KVL section, with the embedding
provider unable to embed the query (`ProviderUnavailableError`), and the model calling
`search_knowledge` as it does for a course question.

## Expected

Retrieval is hybrid — a vector arm and a lexical arm, fused (ADR-0005) — and the lexical arm needs
nothing but the database. With the embedder down, the answer should still find its source by its
words, and cite it.

## Actual

Before the fix, the whole turn was the apology:

```
[error] conversation.provider_failed  provider=embeddings retryable=True
delta: "Sorry — I lost that. Could you say it again?"
done:  tool_activity = []
```

No sources, no answer, and not even a record that the search had been tried.

## Root cause

Two layers, each letting the error through:

1. `HybridRetriever.retrieve` ran the vector arm first and did not catch its failure, so the
   lexical arm never ran.
2. The tool executor treats only *expected* failures as tool errors the model can see — a
   `ToolExecutionError`, bad arguments, a timeout — and lets anything else propagate, so a real bug
   is not laundered into a polite "couldn't do that". A provider being down was not on the list,
   so it escaped the tool, the agent loop, and reached the conversation's own `ProviderError`
   handler, meant for the model's own failures: the apology.

## Fix

1. The retriever catches a `ProviderError` from the vector arm, logs
   `retrieval.vector_arm_unavailable`, marks the span `rag.degraded`, and fuses the lexical arm
   alone. A failing reranker likewise leaves the fused order.
2. The executor treats a `ProviderError` from a tool's dependency as expected — an operational
   fact, not a defect — recording the call as `error` ("embeddings unavailable") and handing the
   model "That isn't available right now." so it can answer without the tool.

## Result

With the embedder down, the answer finds and cites "Degraded KVL Notes" through the lexical arm,
and the tool shows as succeeded. Mutation-checked: with the retriever's fallback disabled, both
retrieval tests fail. What is lost is the vector arm's contribution — paraphrase and cross-lingual
matching (FC-004) — for as long as the outage lasts.
