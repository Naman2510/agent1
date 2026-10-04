# FC-019 — One utterance the recogniser could not make sense of stopped it hearing every later one

**Status:** fixed
**Found:** 2026-10-01 · **Phase:** after 10 (the voice loop's first timing with real local speech,
CI tier T2 run #11) · **Component:** stt (the local recogniser's adapter) / voice
**Severity:** major on the local voice stack. One utterance made every later one fail, for every
student on the server process, until the abandoned work drained. The production real-time path is
a managed recogniser (ADR-0002) and is not affected.
**Case IDs:** the voice-loop bench (`scripts/bench_voice_loop.py`, EVALUATION.md §5.4): multi-hi-01,
multi-hi-02, multi-hil-01, multi-hil-02. `test_eval_stt.py`: "the adapter transcribes the whole
utterance once it ends" (one decode, within a budget).

## Input

The voice dataset's 24 one-question cases (12 one-sentence, 12 two-sentence), played in real time
into the production `VoiceSession`. The recogniser is faster-whisper `small` (int8, beam 5, language
detected per utterance), decoding as Whisper does by default. The model answers at once and eSpeak
NG speaks. T2 run #11 at d8ef722, on a GitHub-hosted runner with an Intel Xeon 6973P-C (4 vCPUs).

## Expected

Every question answered. A transcript within the session's 10 s wait (`stt_final_timeout_ms`,
FC-009), and a slow utterance delaying nobody but itself.

## Actual

```
cases       24 (single, multi_sentence), answered turns 20
            3 turns interrupted by the rest of their question, 2 answered merged with it
            never answered: multi-hi-01, multi-hi-02, multi-hil-01, multi-hil-02
```

The four never answered are every two-sentence question in Hindi and in romanized Hindi, the last
four cases the bench plays. From 11:01:20, the transcript of every utterance failed, each at exactly
the session's wait, six in a row:

```
11:01:20 voice.utterance_ended  reason=speech_end speech_ms=2080
11:01:30 voice.stt_failed       ProviderUnavailableError: no final transcript within 10000 ms
11:01:32 voice.utterance_ended  reason=speech_end speech_ms=1472
11:01:43 voice.stt_failed       ProviderUnavailableError: no final transcript within 10000 ms
   … two more Hindi utterances, then multi-hil-01's two, each the same …
11:02:19 voice.utterance_ended  reason=speech_end speech_ms=2496
11:02:29 voice.stt_failed       ProviderUnavailableError: no final transcript within 10000 ms
```

Before 11:01:20, 19 of the 20 transcripts took at most 2.5 s. The slowest, 7.0 s, was a
one-sentence Hindi question's. The last three failures were romanized Hindi, which eSpeak's English
voice reads. Earlier in the same run, a question of that kind was answered after a
transcript of about two seconds.

## Root cause

Two properties of the local recogniser, each visible in its library's own code, combined:

1. **Whisper's decoding has no bound on audio it cannot make sense of.** When a decode looks wrong
   (too repetitive, or too unlikely), faster-whisper decodes the whole utterance again, at each of
   five rising temperatures in turn, each pass up to the model's 448-token limit. eSpeak's Hindi is
   such audio: Whisper hears it as other languages, or as repetition (FC-005). One such utterance
   took longer than the session waits. That was the first failure: at 11:01:20 the previous
   transcript had arrived after 2.3 s, so nothing was queued ahead of it.
2. **The wait ends; the work does not.** When the session gives up, it cancels its task (FC-009),
   but the decode runs on in its thread: CTranslate2's `generate` cannot be stopped once started.
   The model has one worker (`num_workers=1`), so it serves one decode at a time. And it is one
   model per process (`load_model` is cached), shared by every connection. Each later utterance
   queued behind the abandoned decodes, and timed out too, including romanized Hindi that had been
   transcribed in about two seconds with nothing ahead of it.

FC-009's fix assumed ten seconds was "past any healthy recogniser, the local faster-whisper on CPU
included". For Whisper's own decoding of audio it cannot make sense of, it is not.

## Fix

`app/providers/stt/faster_whisper.py`, at 139dab6. The adapter decodes once, at temperature 0 with
no retries. It also stops at a length no speech of that duration needs: 32 tokens plus 20 for each
second of audio, at most 224, Whisper's usual cap. The rate leaves room: the voice dataset's Hindi
runs at up to 13 characters a second, and Devanagari can take a token or more a character.
Repetition, the way Whisper fails, ran on to the model's limit without a bound. The app (`build_stt`)
and the bench build the adapter with these defaults.

The stt suite measures both ways, and keeps its history. A config that says nothing about decoding
gets Whisper's own, as before, so `stt.toml`, `stt-language-hint.toml` (EXP-013) and their baselines
are unchanged. `stt-live.toml` measures the bounded decoding, and a test holds it to the adapter's
defaults.

## Result

T2 run #12, at 139dab6, on an AMD EPYC 7763. The bench answered every question, with no error sent
to the student:

```
cases       24 (single, multi_sentence), answered turns 24
            5 turns interrupted by the rest of their question, 5 answered merged with it

stage               n   p50 ms   p95 ms   max ms
stt_final_ms       24     3672     3833     4740
```

The slowest transcript took 4.7 s, inside the session's 10 s wait with room to spare. The next run
(#13, the same code on an Intel Xeon Platinum 8370C) answered every question too, the slowest
transcript in 4.1 s. The five
two-sentence questions ended at their pause were each answered as one question, merged (ARCHITECTURE
§5.6), the voice suite's same five cut-offs. The two runs' times are not comparable with each other:
different CPU models, and run #11's was much the faster.

What the bound costs, from the same run, on the CPU model the recogniser's baselines are enforced
on. `stt` reproduced its baseline exactly, and `stt-live` recorded its first:

| Decoding | All WER | English | Hindi | Romanized Hindi |
|---|---|---|---|---|
| Whisper's own (`stt.toml`) | 0.447 | 0.123 | 1.425 | 0.941 |
| Once, within the budget (`stt-live.toml`) | 0.440 | 0.123 | 1.383 | 0.941 |

Nothing, in English or romanized Hindi: the same WER and CER to four places, and 30 English
transcripts word for word in both. Hindi's WER fell a little, from 1.425 to 1.383, and its CER from 1.198 to
1.192. Both are still above 1, more words wrong than were spoken, and Hindi is still not heard as
Hindi (FC-005).

**Not fixed:** a decode still cannot be stopped. On a machine slow enough that one bounded decode
outlasts the session's wait, the next utterance would still wait behind it. The bound makes that
far less likely; it does not make it impossible. A recogniser in a process of its own, which could
be killed, would, and so would the managed streaming recogniser the real-time path is planned to
use (ADR-0002).
