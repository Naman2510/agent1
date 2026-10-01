# FC-006 — A speech-recognition baseline no other machine could reproduce

**Status:** fixed on one CPU model, and accepted as a limitation across CPU models. Every T2 run on
the AMD EPYC 7763 since oneDNN was pinned agrees to the last digit: five runs, the latest on 1
October. Four other CPU models have differed. The latest two had every pin in place, and those two,
both Intel, agree with each other to the last digit. No library in the arithmetic promises the same
numbers across vendors. So a baseline computed on another model is compared, not enforced (below).
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

**Not yet shown:** that this was the only cause. The next section explains why it cannot be
assumed.

## What the libraries promise, and what T2 now checks (Phase 9)

T2's sixth run (d7f415e, 30 September) was the first with the oneDNN cap. It ran on an AMD EPYC
7763 again. Its log shows oneDNN running the convolutions with `brgconv:avx2`, as predicted, and
both baselines matched to the last digit. EXP-013 matched too: +0.0725, 95% CI [+0.0265,
+0.1271], 8 better and 0 worse. So the cap changes nothing on the CPU model that wrote the
baselines. That is three runs agreeing on one model for `stt-language-hint` (bdcad75, f94fccd,
d7f415e) and two for `stt`.

Whether an Intel runner now agrees is still unseen. Waiting for one would no longer settle the
question anyway, because of what the two libraries document:

- **Intel oneMKL.** Its conditional numerical reproducibility guide supports only the AUTO and
  COMPATIBLE modes on non-Intel CPUs. On those CPUs an AVX2 setting runs the AUTO branch instead,
  and results may differ. So the pin `MKL_CBWR=AVX2` is honoured on the Intel runners only. The
  AMD baselines were computed on MKL's automatic path, and their recorded `numerics` name the
  setting, not the path that ran. Nothing warns about it: T2's machine report looks for MKL
  warnings, and no AMD run has shown one.
- **oneDNN.** Its guide promises bit-identical results from run to run only when the hardware and
  the software environment are identical. Capping its instruction set removed the one difference
  measured. It does not make an AVX-512 Xeon the same hardware as an EPYC, and nothing documents
  that the kernels' other choices are the same on both.

MKL's COMPATIBLE mode would cover MKL, at 5.4 times the cost in the local measurement, but not
oneDNN. A tolerance wide enough for the Intel run (Hindi WER moved by 0.17) would hide a real
regression. So a baseline now holds exactly on the CPU model that computed it, and T2 treats
every other model as evidence rather than a verdict:

- **Every stt run records its CPU model** (`summary.machine`, from `/proc/cpuinfo`), and the two
  committed baselines record the AMD EPYC 7763 that computed them, from their runs' logs. Each is
  marked `amended`.
- **`check_baseline`** holds a run exactly to a baseline from its own CPU model, as before. On
  another model the run is still compared. If it agrees, the check passes and names both
  machines. If it differs, the result is exit code 3: the differences are listed, and T2 raises a
  warning instead of failing. A regression and the hardware cannot be told apart there. A failure
  anywhere else in the same run is never hidden behind a code 3 (`recording.worst`).
- **The numbers in EVALUATION.md and EXPERIMENTS.md are the AMD EPYC 7763's.** Four of the six
  T2 runs that logged their CPU were given that model, so it is the one an exact check is most
  likely to get.

The next T2 run on an Intel runner will show whether the cap was the only cause. If it was, the
check passes and says it matched on both machines; if not, it warns with the differences. Either
way T2 no longer turns red because of the CPU it happens to be given, and it still catches a
changed transcript on the CPU the baselines came from.

## A third CPU model, and two more steps that follow the CPU (Phase 9)

The first run with the new check (ac725cb) was given a third CPU model: an AMD EPYC 9V74, a Zen 4
with AVX-512. Every pin was in place, and oneDNN again ran `brgconv:avx2`. Both baselines differed,
and the check did what it was built for: it listed the differences, exited 3, and T2 warned
instead of failing.

```
                         EPYC 7763 (baseline)   Xeon 8573C (4b3159a)   EPYC 9V74 (ac725cb)
stt              en WER  0.1227                 0.1273                 0.1273
                 hi WER  1.4255                 1.2553                 1.4468
                 all WER 0.4465                 0.4245                 0.4497
stt-language-hint hi WER 0.9574                 0.9362                 1.0
EXP-013 gain             +0.073                 +0.047                 +0.067
```

So the pins do not make two CPU models agree, even two from one vendor. EXP-013's decision was
the same on all three (inconclusive), with the gain between +0.047 and +0.073.

The two AVX-512 machines gave the same English WER, which points at a step that uses AVX-512
wherever it exists and that no pin reached. The recogniser's input is such a step. faster-whisper
computes the log-mel features in numpy, before CTranslate2 sees anything. Measured on an AVX-512
Xeon over 12 of the dataset's clips, each of these changed the features:

- numpy's own kernels (`np.abs`, `np.log10`): it dispatches to AVX-512 where it finds it;
- OpenBLAS, which runs the mel filterbank's matrix product: SkylakeX kernels on AVX-512, and its
  thread count, since one thread and four gave different features.

Four settings gave four different feature hashes. Forcing OpenBLAS's `Zen` core type gave its
`Haswell` kernels, with the same features as `Haswell`. These are read when numpy loads, before the
suite can pin anything, so T2 starts the process with them (`STARTUP_PINS`):
`NPY_DISABLE_CPU_FEATURES=X86_V4,AVX512_ICL,AVX512_SPR`, `OPENBLAS_CORETYPE=Haswell` and
`OPENBLAS_NUM_THREADS=4`. The summary records them, and a test holds the workflow's values to the
suite's. Each is what the EPYC 7763 chose unpinned: it has no AVX-512, and numpy ignores disabling
what a CPU lacks; OpenBLAS gives a Zen CPU its Haswell kernels; its runner has four vCPUs. So the
baselines keep their numbers, amended again. T2 now logs numpy's and OpenBLAS's choices with and
without the pins. The next run (eb67b97) was on the 7763. Unpinned, numpy dispatched to `X86_V3`
only and OpenBLAS chose its Haswell kernels on 4 threads, the same as pinned. Both baselines
matched to the last digit, with the new pins recorded, and so did EXP-013 (+0.0725).

**Not yet shown:** whether the AVX-512 runners now agree with the 7763. MKL still runs its
automatic path on AMD and its AVX2 mode on Intel, and oneDNN still promises nothing across
hardware. So the check stays as it is: exact on the baselines' CPU model, compared on the rest.

## A fourth CPU model, with every pin in place (1 October)

T2 run #11 (d8ef722) was given an Intel Xeon 6973P-C, with AVX-512. Its machine report shows the
startup pins taking effect. Unpinned, numpy would dispatch to `X86_V4`, `AVX512_ICL` and
`AVX512_SPR`, and OpenBLAS would choose its SkylakeX kernels. Pinned, numpy used `X86_V3` and
OpenBLAS its Haswell kernels, on 4 threads, as on the 7763. Both baselines still differed:

```
                         EPYC 7763 (baseline)   Xeon 6973P-C (d8ef722)
stt              en WER  0.1227                 0.1227
                 en CER  0.0641                 0.0651
                 hi WER  1.4255                 1.1702
                 all WER 0.4465                 0.4088
stt-language-hint hi WER 0.9574                 0.9787
EXP-013 gain             +0.073                 +0.031
```

English WER now agrees to four places, where both earlier AVX-512 runners had 0.1273. Its CER does
not quite, so not every English transcript is the same. Hindi is far apart. No unpinned step is
known. What remains is what the libraries themselves say: MKL runs a different path on Intel than
on AMD, and oneDNN promises nothing across hardware. EXP-013's decision was the same on a fourth CPU model (inconclusive, 5 better and 0
worse). The three runs on the 7763 the same day (#9, #10, #12) reproduced both baselines exactly.

So the answer to "not yet shown" is no: the AVX-512 runners do not agree with the 7763, even with
every pin. The check stays exact on the baselines' CPU model and compared on the rest, which is what
the libraries promise.

## A fifth: two Intel generations agree with each other (1 October)

T2 run #13 (49e458b) was given an Intel Xeon Platinum 8370C, an Ice Lake, two generations before
the 6973P-C. Its pins took effect as #11's did. Every metric of `stt` and `stt-language-hint` came
out exactly as on the 6973P-C, every difference from the 7763 the same to the last digit, and so did
EXP-013 (+0.0308, [+0.0043, +0.0694], 5 better and 0 worse). The two differ from the 7763 alike.

That fits what the libraries say, and is the first thing that does. oneMKL documents its AVX2
reproducibility mode as giving the same results on Intel processors, while on others it runs the
automatic path. So with every pin, the arithmetic now seems to follow the vendor, not the model.
Two Intel models are not a promise, though, and AMD's are not covered by one. If more Intel runs
keep agreeing, a second set of baselines computed on Intel would let T2 enforce, not just compare,
on every Intel runner. Until then the check is as above.
