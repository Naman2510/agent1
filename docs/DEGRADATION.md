# Graceful degradation

**Status:** Phase 9. Every row below is pinned by a test that takes that dependency down and asserts
what the student gets — `backend/tests/integration/test_degradation.py` unless another file is
named. Rows marked **fixed** failed that test when it was first written; what happened before is
recorded next to what happens now.

Three rules decide each row:

1. **An answer is worth more than a control.** A dependency that only guards or counts (rate
   limits, the spend cap, the voice allowance, the short-term window) is skipped when it is down,
   loudly (a warning in the log), and the student is answered.
2. **Nobody waits in silence without being told.** Every wait on a provider is bounded, and what
   comes after the bound is said to the student: an apology, or "the rest is in text".
3. **A failure costs a turn, never the session.** Whatever broke, the next question works.

## The matrix

| Dependency | Failure | What the student gets | What is recorded | Test |
|---|---|---|---|---|
| **Language model** | unreachable, or errors before any text | The apology (`FAILURE_REPLY`), spoken in voice, shown in text; the next question works | question and apology | `test_llm_down_a_voice_student_hears_an_apology_and_can_ask_again`; `test_chat_turn.py::test_a_provider_outage_degrades_to_a_spoken_apology_and_is_still_recorded` |
| | errors mid-answer | What was said so far, a word break, then the apology — **fixed**: the apology was glued to the last word, and spoken that way ("voltages aroundSorry") | as shown | `test_llm_lost_mid_answer_keeps_what_was_said_and_apologises_for_the_rest` |
| | accepts the request, then says nothing | The apology after `llm_stall_seconds` (20 s) without an event; the request is cancelled — **fixed**: the SDK's timeout bounds each read (30 s) and retries twice, so the silence could last a minute and a half | question and apology | `test_llm_that_never_answers_is_given_up_on_with_an_apology` |
| | declines (refusal) | `REFUSAL_REPLY` | question and reply | `test_chat_turn.py` |
| **Speech recognition** | fails mid-utterance | `stt_failed`: "Sorry — I didn't catch that. Could you say it again?"; listening again; no turn spent | nothing | `test_voice_session.py::test_a_recogniser_that_fails_mid_sentence_is_reported_and_the_session_listens_again` |
| | never returns a final transcript | The same, after `stt_final_timeout_ms` (10 s) — **fixed**: the wait was unbounded, on the connection's receive path, so the session stopped hearing anything at all. Giving up frees the session but not a local model, whose decode runs on and holds up the next one, so the local recogniser bounds each decode (FC-019) | nothing | `test_a_recogniser_that_never_finishes_is_given_up_on_and_the_session_listens_again`; T2's voice-loop bench (FC-019) |
| **Speech synthesis** | fails, or produces no audio for `tts_stall_timeout_ms` (5 s), at any sentence | The answer goes on as text (it is already streaming as `llm.delta`), one `tts_failed` notice, and the turn ends as it would have; the voice is tried afresh next turn — **fixed**: the turn ended in `turn_failed` and the text stopped where the voice did | the whole answer | `test_a_voice_that_is_lost_mid_answer_finishes_the_answer_in_text` (fails, hangs); `test_a_voice_lost_before_the_first_word_still_delivers_the_answer_in_text` |
| **Embeddings** | the query cannot be embedded | Retrieval goes on with the lexical arm alone, and the answer still cites its source — **fixed**: the error escaped the tool and the whole turn became the apology | answer, sources, tools | `test_embeddings_down_retrieval_falls_back_to_the_lexical_arm`; `test_embeddings_down_an_answer_still_finds_and_cites_its_source` |
| **Reranker** | fails | The fused order, unreranked | — | `test_reranker_down_retrieval_keeps_the_fused_order` |
| **Any tool's provider** | a `ProviderError` inside a tool | A tool error the model answers around ("That isn't available right now") — **fixed**: as for embeddings | tool call as `error` | `test_tool_executor.py::test_a_tool_whose_provider_is_down_is_an_error_the_model_can_answer_around` |
| **Redis** | unreachable | Everything answered and recorded. Rate limits, the spend cap and the daily voice allowance are not enforced, each logged at warning; the short-term window is read from Postgres; readiness says `degraded` with 200 — **fixed**: every priced turn ended in an error *after* it had been answered (the spend counter's write), a spend cap refused every turn, no voice connection could open (the allowance check), and readiness went 503, which would take every instance out of rotation | everything; the usage counters miss the outage's increments (each turn's usage is still stored with its message) | `test_redis_down_*` (six); `test_rate_limit.py::test_fails_open_when_redis_is_unavailable` |
| **PostgreSQL** | unreachable | HTTP `503 service_unavailable` with `Retry-After: 5`, naming nothing; readiness `unavailable` (503), liveness 200 — **fixed**: an unhandled `ConnectionRefusedError`, a 500 | nothing (it is the record) | `test_database_down_requests_are_refused_as_unavailable_not_as_a_crash` |
| | drops a voice session's connection (a restart, a failover) | That turn fails (`turn_failed`); the next one works — **fixed**: the session's transaction was left needing a rollback, and every later turn failed with `PendingRollbackError` until the student reconnected (the class of D8-04) | the next turn | `test_a_database_connection_lost_mid_session_costs_one_turn_not_the_session` |

## The bounds

| Setting | Value | Why this value |
|---|---|---|
| `llm_stall_seconds` | 20 s | Between events, not over the whole answer, so a long answer that keeps arriving is never cut. Far past a healthy first token (the budget is 0.8 s), far short of the SDK's 30 s per read times three attempts. A turn that thinks for longer than this before saying anything is given up on — a voice student would have given up first. |
| `stt_final_timeout_ms` | 10 s | Past any healthy recogniser, the local faster-whisper on CPU included (CI's first stt run heard 66 short utterances in about four minutes, model loading and all), and short of a student concluding the session is dead. Whisper's own decoding of audio it cannot make sense of was not inside it (FC-019); decoding once, within a length budget, the slowest transcript in T2's voice-loop run took 4.7 s (EVALUATION.md §5.4). |
| `tts_stall_timeout_ms` | 5 s | Between audio pieces. The budget for a first byte is 0.35 s; five seconds of silence mid-answer is already a failure the student noticed. |
| Tool timeouts | per tool | Unchanged from Phase 6 (`ToolDefinition.timeout_seconds`). |

## Deliberate trade-offs

- **The spend cap is not enforced while Redis is down.** Refusing every turn because the counter is
  unreadable would make an accounting outage a product outage. The cost is bounded by the outage's
  length, and no spend goes unrecorded: each turn's usage is stored with its message, so the month's
  counter can be rebuilt from `messages.token_usage`. The rate limiter made the same choice in
  Phase 2.
- **A lost voice is not an error state.** ARCHITECTURE §4.1's `ERROR → LISTENING: recovered (spoken
  apology)` cannot apply when the voice is what failed; the answer continues as text instead.
- **What a barged-in turn records after its voice was lost** is only what was *heard* — the ledger
  counts audio, not text on a screen. Conservative, as it is everywhere else (§5.3).

## Not covered

- **Real providers failing in their own ways.** Every failure here is a fake failing in a stated
  way: raising, or going quiet. A real recogniser returning confident nonsense, or a synthesiser
  returning noise, is not a failure these tests can see; the evaluation suites are where that shows.
- **A voice connection opened while the database is down** is refused at the handshake. Closing a
  WebSocket before accepting it cannot carry a reason to a browser, so the client sees only that
  the connection failed.
- **No turn is retried for the student.** They are told, and ask again; retrying a question behind
  their back would answer it twice when the first attempt had in fact got through.
- **Load.** Behaviour under many concurrent sessions is a separate question (Phase 9, load).
