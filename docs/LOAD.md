# Load: many voice students on one server

**Status:** Phase 9. This document covers what one backend process does as simultaneous voice
students are added. It was measured with `backend/scripts/load_voice.py` on the development
container (4 vCPUs, shared with the load client), 27–30 September 2026. Load testing found four
problems. Three were defects: the pool admitted only fifteen students (FC-015), a cancelled answer
lost its record (FC-016), and a rolled-back turn left the connection unmetered (FC-017). The fourth
was a cost: every connection carried its own copy of the VAD model. All four are fixed, and the
numbers below come from before and after the fixes. In short: one process now serves about 50
connected voice students with first audio within 0.7 s of a single student's (p95), and it is
saturated at 75.

## How it was measured

- **The server** is the application as the image runs it (`uvicorn app.asgi:app`: one process,
  one event loop), in a process of its own. It uses the real voice WebSocket endpoint and the real
  Silero VAD, with PostgreSQL 16 and Redis 7 on the same machine. The load client runs in another
  process.
- **A student** registers, opens a session, connects the voice socket and asks three questions.
  Each question is a real recording of speech (`datasets/v1/voice/parts/single-en-01-a.wav`, 2.0 s),
  sent in 20 ms frames in real time, as a microphone does. The student then keeps sending silence,
  plays the answer back at real speed, and acknowledges playback every 200 ms, as the browser
  does. Between questions there is half a second of silence. Start times are spread over the first
  two seconds. A student waits up to 30 s for an answer, then moves on to its next question, which
  barges in.
- **Fakes.** The recogniser answers at once, and so does the synthesiser. The model is paced like a
  real one, 0.8 s to its first token and then 150 characters a second, but it never slows down under
  load, as a real API may. The intent classification call and the memory extractor's call went to
  the unpaced default fake, and no corpus was ingested, so no retrieval ran. These numbers therefore
  describe *our server* under load: its event loop, the VAD on every 32 ms window of every
  connection, the database and Redis. They say nothing about a provider's latency.

What the columns mean:

| Column | Meaning |
|---|---|
| Connected | Students whose WebSocket handshake completed (the client gives up after 10 s) |
| Turns complete | Answered and heard to the end: audio arrived, and the session went back to listening |
| First audio | From the end of the student's speech to the answer's first audio at the client. For one student about 1.9 s: the 0.5 s end-of-speech wait, the model's paced 0.8 s, and the first sentence at 150 characters a second |
| Loop lag | How late a 50 ms timer inside the server fires, i.e. how long any piece of work (a frame, a handshake) waits for the event loop |
| CPU | The server process, as a percentage of one core. It has one event loop, so 100% is its ceiling |

## Results

**Before the fixes** (the harness's first run, 27 September):

| Students | Connected | Turns complete | First audio p50 / p95 | Loop lag p99 | CPU | Peak RSS |
|---|---|---|---|---|---|---|
| 1 | 1 | 3 / 3 | 1880 / 1887 ms | 2 ms | 5% | 315 MB |
| 10 | 10 | 30 / 30 | 1889 / 1905 ms | 36 ms | 31% | 408 MB |
| 25 | **15** | 45 / 75 | 1908 / 1991 ms | 33 ms | 43% | 461 MB |
| 50 | **15** | 45 / 150 | 1900 / 1967 ms | 24 ms | 41% | 540 MB |

**After the three defect fixes (FC-015 to FC-017), with each connection still loading its own VAD
model:**

| Students | Connected | Turns complete | First audio p50 / p95 | Loop lag p50 / p99 | CPU | Peak RSS |
|---|---|---|---|---|---|---|
| 1 | 1 | 3 / 3 | 1872 / 1886 ms | 0.5 / 2 ms | 4% | 328 MB |
| 10 | 10 | 30 / 30 | 1890 / 1904 ms | 0.5 / 9 ms | 27% | 476 MB |
| 25 | 25 | 75 / 75 | 1904 / 1935 ms | 0.6 / 23 ms | 59% | 626 MB |
| 50 | 50 | 150 / 150 | 4122 / 9624 ms | 6 / 193 ms | 94% | 881 MB |
| 75 | 61 | 156 / 225 | 6789 / 13870 ms | 54 / 308 ms | 93% | 993 MB |
| 100 | 63 | 162 / 300 | 6710 / 13798 ms | 44 / 317 ms | 91% | 1012 MB |

**After sharing the VAD model** (the final code; 1 and 10 students were not re-run):

| Students | Connected | Turns complete | First audio p50 / p95 | Loop lag p50 / p99 | CPU | Peak RSS |
|---|---|---|---|---|---|---|
| 25 | 25 | 75 / 75 | 1901 / 1944 ms | 0.4 / 9 ms | 48% | 388 MB |
| 50 | 50 | 150 / 150 | 2224 / 2552 ms | 0.7 / 34 ms | 78% | 395 MB |
| 75 | 75 | 225 / 225 | 4808 / 6540 ms | 4.5 / 147 ms | 92% | 402 MB |
| 100 | 99 | 155 / 300 | 10705 / 16571 ms | 44 / 436 ms | 93% | 403 MB |

At 50 students, an earlier run of the defect-fixed code gave first audio p50 3165 ms and p95 6388 ms
at 88% CPU, against 4122 / 9624 ms at 94% above. Close to saturation, waits are very sensitive to
small differences in load, so one run at a level is an indication, not a figure to plan by.

## What load found

### 1. The database pool was the limit: fifteen students (FC-015)

At 25 and at 50 students, exactly fifteen connected, and the rest timed out in the handshake with
the server at 41% of a core. Fifteen is the pool (10 + 5 overflow). Each connection's pre-accept
lookups began a transaction that was held until its first turn's commit, idle or not. Each turn then
held its connection through the model's answer and the whole of the playback. Now the handler
commits before it accepts, and a turn hands its connection back before every wait on a model.

### 2. A cancellation during the answer's write lost it (FC-016)

At 100 students, 10 turns in one run and 7 in the next ended with a broken transaction: a flush or
a commit cut off part-way by a cancellation. D8-04 made every write of a turn finish before a
cancellation proceeds, except the last one, the answer's own record. A barge-in, or a student
leaving, that landed while that record was being written cut it off, and the answer the student had
heard was never recorded. Under load that write waits for a pooled connection, which is why only
load hit it. The record, its commit, its cost and the memory tasks it starts are now one unit that
a cancellation waits for.

### 3. A rolled-back turn left the connection's audio unmetered (FC-017)

Each of those rollbacks expired the rows the connection's database session had loaded, including
the student's. At the close, the handler read the student's id from that expired row, which needs a
query and fails there (`MissingGreenlet`). So the daily voice allowance never recorded the
connection's audio, ten times in one run. The id is now read once, as a value.

### 4. Every connection loaded its own copy of the VAD model

A profile of the server at 50 students (py-spy, 30 s at 100 Hz) found the VAD
(`SileroVoiceDetector.probability`) in 73% of the busy samples, 71% of a core, most of it inside
ONNX Runtime's `run`. The database, Redis, logging and the conversation logic were each under 1%.
Each connection built its own ONNX Runtime session, measured at 9.7 MB and 36 ms each (114 ms for
the first):

- **Memory.** 9.7 MB per session was most of the ~12 MB that each student added.
- **Loop blocking.** The 36 ms ran on the event loop, so a hundred students connecting within two
  seconds put 3.6 s of blocking work in front of every other student's audio.
- **CPU per window.** In isolation, one window costs 0.22 ms (the mean over 3,000; ARCHITECTURE
  §9.1 recorded 0.12 ms on 18 September, and what changed between the two measurements was not
  isolated). Under load it cost about twice that: 71% of a core over 50 × 31 windows a second is
  about 0.45 ms each. Fifty copies of the same weights competing for the CPU's caches would explain
  the difference, and sharing one copy removed most of it.

The model holds no state (each detector passes its recurrent state and context in and takes them
back), so one session per process now serves every connection
(`app/voice/vad.py::_shared_session`). A test checks that a detector hears exactly the same whether
or not another detector runs on the shared model between its windows. The effect at 50 students:

| | Own model per connection | Shared model |
|---|---|---|
| First audio, p50 / p95 | 4.1 / 9.6 s (3.2 / 6.4 s in an earlier run) | 2.2 / 2.6 s |
| CPU, of one core | 94% | 78% |
| VAD share, from the profile | 71% of a core, ~0.45 ms a window | 46% of a core, ~0.29 ms a window |
| Peak memory | 881 MB | 395 MB |

## Where one process stops

- **The event loop, not the database.** After the fixes the pool is never the limit. The process's
  one core is, and the VAD is most of what fills it: every connected student costs a VAD run every
  32 ms, whether talking or not, because the browser streams the microphone for as long as the
  session is open.
- **Up to 25 students, nobody waits longer than a student alone:** first audio p50 1.90 s against
  1.87 s, with a p95 of 1.94 s. **At 50**, the median is 0.35 s longer (2.2 s) and the p95 0.7 s
  longer (2.6 s), with the process at 78% of a core. **At 75** the process is saturated (92%): every
  turn still completes, but first audio is 4.8 s at the median. **At 100**, half the turns ran past
  the client's 30-second wait.
- **The measurement is the server's.** The load client kept pace throughout: it never fell more than
  34 ms behind real time while sending audio.
- **Memory** barely grows with students any more: 388 MB at 25 students, 395 MB at 50, 403 MB at
  100.

## Capacity, as deployed

The image runs one process (`infra/docker/backend.Dockerfile`: `uvicorn app.asgi:app`, no
`--workers`). One process serves about 50 connected voice students before their waits grow
noticeably. Plan for fewer: this server shared a 4-vCPU machine with its load client, and a real
deployment adds work the fakes here did not do, such as streaming each student's audio to a
recogniser and receiving synthesised speech.

Beyond that, add processes: replicas behind a router that keeps each session on its process
(ARCHITECTURE §15), or uvicorn's `--workers`. Each process has its own pool of up to 15
connections, so PostgreSQL's default `max_connections` of 100 allows six such processes before the
pools alone exhaust it. After the fix the pool is only an upper bound: a process holds connections
only while turns are actually querying.

Two changes could raise the per-process number, and each should be measured before it is adopted:

- Running the VAD for many connections in one batched call, which spreads each call's fixed cost
  over many windows. How large that cost is was not measured.
- Skipping the model on digital silence. This changes what the model hears (its recurrent state
  would skip those windows), so the voice suite (EVALUATION.md §4) would have to be re-run first.

## Not measured

- **Real providers**: their latency under load, their own rate and concurrency limits (a streaming
  recogniser's concurrent-stream cap per account, for one), and their failures under load. Every
  provider here is a fake.
- **Anything but one process on one machine**: several workers, a real network (everything ran over
  loopback), TLS, a real browser.
- **The text path** (HTTP and SSE), the intent call's own latency, retrieval against an ingested
  corpus, tool calls, and the memory extractor's model call.
- **Long sessions**: each student asked three questions. Memory over an hour-long session was not
  measured.

## Reproducing

```
cd backend
python scripts/load_voice.py --levels 1,10,25,50,75,100 --questions 3 --json results.json
```

It needs PostgreSQL and Redis running, and a migrated database of its own, named by
`VAANIOS_LOAD_DATABASE_URL` (default: the local `vaanios_load`).
