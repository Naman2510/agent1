# FC-006 — A speech-recognition baseline no other machine could reproduce

**Status:** open — reproduced exactly on a second runner of the same CPU model; the first Intel
runner did not reproduce, and one cause of that is found and pinned (below); whether it is the
only one waits on the next Intel runner
**Found:** 2026-09-27 · **Phase:** 8 (PHASE_8_AUDIT D8-15) · **Component:** evaluation (stt)
**Severity:** major — a baseline that does not reproduce cannot catch a regression
**Case IDs:** the whole `stt` suite, dataset v1

## Input

The same commit's `stt` config (faster-whisper `small`, int8, beam 5, auto language), the same 66
audio files, run by CI tier T2 twice on two GitHub runners: first to write the baseline (ac96111),
then to check it (31603aa).

## Expected

Identical numbers: same model, same weights, same audio, same settings.

## Actual

```
                first runner (wrote)   second runner (checked)
all   WER       0.4465                 0.4182
hi    WER       1.383                  1.2553
en    WER       0.1273                 0.1182
```

The check failed, as it should have. English moved by three words in ~330; Hindi — never
recognised as Hindi (FC-005) — moved by far more.

## Root cause

Two mechanisms, both measured locally on a Whisper-shaped CTranslate2 model with random weights
(the real weights cannot be downloaded in the development environment):

1. **Whisper samples, unseeded.** When a transcript looks wrong — too repetitive, or too unlikely —
   faster-whisper retries at rising temperatures (0.2 … 1.0), sampling with CTranslate2's random
   generator, which is seeded from the operating system. Two processes on the same machine sampled
   different tokens. Hindi, decoded in the wrong language, triggers the fallback often, which fits
   it moving most. And `ctranslate2.set_random_seed` alone does not fix it: the generator is created
   once per model worker thread, on first use; reseeding afterwards had no effect, so each
   utterance's randomness depended on how much the utterances before it had drawn.
2. **The arithmetic follows the CPU.** CTranslate2 picks its kernels by instruction set, and at
   GENERIC, AVX, AVX2 and AVX512 the same encoder input gave four different outputs. By default it
   decides from the CPU's vendor whether to use Intel MKL at all (`CT2_USE_MKL`), and MKL picks its
   own code path per CPU:
   its AVX2 and COMPATIBLE modes each differed from its default on an AVX-512 machine. GitHub's
   hosted runners are not all one CPU model; which ones the first two runs had was not logged.
   (Thread counts of 1, 2, 4 and 8 gave identical numbers.)

## Fix

`backend/eval/suites/stt.py`, at bdcad75:

- Seeded (`seed = 0` in the config), and each utterance heard by a model of its own, so its
  sampler starts at the seed whatever came before — every case independent of every other, which
  an experiment's per-case comparison also needs.
- The arithmetic pinned before either library starts: CTranslate2 at AVX2, MKL for every matrix
  product, MKL's reproducible mode at AVX2 (`NUMERICS`), recorded in each run's summary so a
  baseline says how its numbers were computed. MKL's COMPATIBLE mode is the one documented as
  identical across vendors, but ran 5.4 times slower than the default in the local measurement
  (AVX2: 1.2 times), so AVX2 was tried first.
- T2 now logs the runner's CPU and the kernels chosen under the pins.

## Result

T2's first pinned run (bdcad75) ran on an AMD EPYC 7763: CTranslate2 chose AVX2 and MKL for every
product, with no MKL warning, and wrote `stt-language-hint`'s baseline. The next (f94fccd) ran on
another runner — also an AMD EPYC 7763 — and reproduced it exactly, every metric. So the sampling
fix is shown: before it, two runs could not agree even in principle. The pins are not yet shown
doing their job across vendors: both runners were the same CPU model, and whether an Intel runner
gives the same numbers waits for the first one T2 is given. The cost: 12 min 46 s per config,
against about four minutes unpinned — which led T2 to run each config once rather than twice
(f94fccd).

If an Intel runner disagrees, the fallback is MKL's COMPATIBLE mode (slower, but documented as
vendor-independent), and failing that a stated tolerance — which would be recorded here as the
limit of what the baseline can catch.

## The first Intel runner (Phase 9)

T2's fifth run (4b3159a, 29 September) was the first on an Intel CPU: a Xeon Platinum 8573C,
with AVX-512. The library versions were identical to the AMD runs (ctranslate2 4.8.2,
faster-whisper 1.2.1), and the kernels reported were the same (CTranslate2 at AVX2, MKL for every
product). Neither baseline reproduced:

```
                         AMD EPYC 7763 (baseline)   Intel Xeon 8573C
stt              en WER  0.1227                     0.1273
                 hi WER  1.4255                     1.2553
                 all WER 0.4465                     0.4245
stt-language-hint hi WER 0.9574                     0.9362
                 hi CER  0.6328                     0.5932
```

EXP-013's comparison on that runner came out +0.047 (95% CI [+0.009, +0.098]), against +0.073
on the AMD runner. The decision is the same (inconclusive), but the gain is not the same number.

**One cause, found.** CTranslate2 carries oneDNN (v3.1.1) inside it, and oneDNN runs the
encoder's two convolutions with kernels it picks for itself: `CT2_FORCE_CPU_ISA` does not reach it.
On an AVX-512 machine its verbose log shows `brgconv:avx512_core`. On the AMD EPYC 7763, which has
no AVX-512, it can only have used AVX2. Measured locally on the Whisper-shaped probe model, on
an AVX-512 Xeon, capping oneDNN at AVX2 changes the encoder's output. `ONEDNN_MAX_CPU_ISA=AVX2` is
now among the pins, and T2 logs the convolution kernel each run used. On the AMD runners the cap
changes nothing, so the committed baselines keep their numbers, with the pin added to what they
record (`amended` in each file).

**Not yet shown:** that this was the only cause. MKL's reproducible mode at AVX2 is documented as
reproducible across Intel processors, and only its COMPATIBLE mode across vendors. The next T2
run on an Intel runner shows whether the numbers now agree. If they do not, the next step is MKL's
COMPATIBLE mode, then a stated tolerance, as planned above. Until then the T2 check is red on any
Intel runner, and the numbers in EVALUATION.md and EXP-013 are the AMD runner's.
