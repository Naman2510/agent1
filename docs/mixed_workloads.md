# Mixed Heterogeneous Workloads (Phase 16)

Phase 15 built a genuinely runtime-decided scheduler (one RISC-V
program, computing engine choice on the CPU per workload) but tested
it on a small, 6-workload stream and found it lost to the naive
"always use the accelerator" baseline -- overhead from computing the
decision, plus one known misprediction, outweighed the benefit. Phase
16 asks the obvious follow-up question: **does that conclusion still
hold at a larger, more varied, more realistic scale?**

## A bigger, still-honest stream

`scheduler/runtime/gen_mixed_workload_demo.py` reuses Phase 15's exact
per-block body generators, decision logic, and `mul32` subroutine
(imported, not copy-pasted, so any future fix applies to both demos)
against a new 12-workload stream: `vecadd` at N=1,2,4,8,16,32; `dot`
at N=4,8,16,32; `matmul` at N=2,4 -- roughly 4-32x the average
per-workload size of Phase 15's stream, while keeping `vecadd` N=1 and
N=2 in the mix once each so the model's one known misprediction still
has a chance to matter.

`matmul N=8` (32885 CPU cycles standalone -- by far the largest single
workload this project has measured) is deliberately excluded. Include
it and it would dominate every program's total so completely that
dynamic/always-accelerator/oracle would all look nearly identical --
not because the comparison became uninteresting, but because one
outlier would be doing all the talking. Leaving it out keeps this
phase's result attributable to the actual question being asked (does
overhead amortize with scale?), not an artifact of one huge workload
swamping everything else.

Correctness (every block's real computed result, spot-checked at
first/last element for arrays, full value for scalars -- these are the
exact same per-block bodies already exhaustively verified in Phase
11/13/15, so this phase's own risk is specifically the multi-block
generation machinery) is verified in
`sim/testbenches/tb_mixed_workload_correctness.sv`, passing under both
Icarus Verilog and Verilator (`make test_mixed_workload_correctness`).

## Real result: the overhead hypothesis holds, but the ceiling was always low

```
make run_mixed_workload_demo
```

| Program | Total cycles |
|---|---|
| Dynamic (runtime decision) | 2590 |
| Always CPU | 10084 |
| Always accelerator | 2366 |
| Oracle (best-per-block, from real data) | 2356 |

Dynamic is still slower than always-accelerator (2590 vs. 2366 -- 9.5%
worse), but that is a dramatic improvement over Phase 15's 26.5% worse
on the small stream -- confirming, with a second real measurement
rather than just a plausible guess, that **the runtime decision's
fixed per-block cost matters proportionally less as each workload does
more real work.**

But the more important, humbler finding is what the oracle column
shows: **even a perfect, zero-overhead scheduler could only have saved
10 cycles on this entire 12-workload stream** (2366 -> 2356). That is
not a Phase-16-specific artifact -- it is a direct consequence of
Phase 13's own dataset (`docs/scheduler.md`): in every measured
workload except `vecadd` at N=1, the accelerator wins, often by a wide
margin (RV32I's lack of a hardware multiplier makes the gap widen fast
for `dot`/`matmul`). A learned scheduler's ceiling is bounded by how
often the "wrong" static choice would actually be made, and for this
accelerator, "always use it" is already correct almost everywhere.

## What this phase does and doesn't establish

- It confirms, with a second real measurement, that Phase 15's
  overhead finding is a genuine SCALE effect, not a one-off artifact
  of that specific small stream -- the relative penalty shrunk
  roughly 3x (26.5% -> 9.5%) between a ~6-cycle-average-per-workload
  stream and a much larger one.
- It shows, honestly, that the reason dynamic scheduling doesn't pay
  off on either stream tested so far is NOT primarily the decision
  overhead (which shrinks with scale, as shown) but the small size of
  the oracle-vs-baseline gap itself: this accelerator design and this
  project's three measured kernels simply don't have much of a
  "sometimes CPU is better" regime to exploit, outside one narrow
  small-N corner.
- It does NOT mean AI-directed scheduling is worthless for
  heterogeneous systems in general -- it means, specifically and
  honestly, that for THIS accelerator (fast, low fixed overhead,
  genuinely faster at nearly everything) and THESE three kernels, the
  opportunity for a scheduler to add value is inherently small. A
  slower or higher-setup-cost accelerator, or a wider variety of
  kernels with more genuine crossover points, would change this
  picture -- a real, appropriately scoped direction for future work,
  not something this phase claims to have already covered.
- The workload stream is still fixed and generated, not a live,
  arbitrary-length runtime queue -- Phase 17's end-to-end demo is
  where this project's full pipeline gets put together and
  documented as a whole system, not where new scheduling capability
  is added.
