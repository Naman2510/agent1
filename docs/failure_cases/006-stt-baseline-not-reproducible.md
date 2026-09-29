# FC-006 — A speech-recognition baseline no other machine could reproduce

**Status:** fixed — reproduced exactly on a second runner; across CPU vendors not yet shown
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
