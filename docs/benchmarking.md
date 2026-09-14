# CPU vs. Accelerator Benchmarking (Phase 11)

This document describes how Phase 11 measures and compares the
pipelined CPU running a computation entirely in software against the
hardware accelerator (`rtl/accelerator/accelerator.sv`, Phase 9/10)
running the same computation, for the same three operations the whole
project has followed since Phase 9: vector add, dot product, matrix
multiply. Every number in `results/accelerator_benchmark_report.md` is
measured from an actual Icarus Verilog simulation -- nothing is
estimated, hand-computed, or presented as a physical-hardware/FPGA
measurement (FPGA resource *estimation*, still not physical execution,
is Phase 12's job).

## Methodology

### Same operands, both implementations

Every operation is benchmarked twice: once as a CPU-only kernel (pure
RV32I software, no accelerator involved) and once driven through the
accelerator via the `ACCEL.*` custom instructions (Phase 10). Both
versions of a given operation use **identical operands**
(`A[i]=i+1, B[i]=i+2` for vecadd/dot; `A[i,j]=i+j+1, B[i,j]=i+j+2` for
matmul) and the same problem size, so the comparison is apples-to-
apples -- see `sim/programs/benchmarks/cpu_vecadd_bench.s` and
`accel_vecadd_bench.s` (and their dot/matmul counterparts) for the
exact assembly.

| Operation | Size |
|---|---|
| vecadd | N=16 |
| dot | N=16 |
| matmul | 4x4 (16 elements -- chosen to match vecadd/dot's element count for a fair three-way comparison) |

### Why the CPU-only kernels need a software multiply routine

RV32I (this project's ISA subset) has no hardware multiplier -- the M
extension isn't implemented. The CPU-only `dot` and `matmul` kernels
therefore compute every product with `mul32`, a real shift-and-add
software multiply subroutine, verified independently in
`sim/programs/benchmarks/mul32_test.s` *before* any benchmark kernel
was written to depend on it (see that file's header comment). This is
expected to -- and does -- make CPU-only `dot`/`matmul` dramatically
slower than the accelerator's one-multiply-per-cycle hardware, which
is exactly the kind of real, measured contrast this benchmarking phase
exists to produce, not something to work around.

**A real bug this uncovered:** the first version of the `dot` and
`matmul` kernels used register `x1` for both a data pointer (`&A[0]`)
and, unintentionally, as the target of `jal x1, mul32` -- RISC-V's ABI
return-address register. The call to `mul32` silently overwrote the
data pointer after the first loop iteration, corrupting every
subsequent array access. This produced a wrong-but-plausible-looking
result (the dot product came out equal to exactly its first term) that
`sim/testbenches/tb_bench_cpu_correctness.sv` caught immediately.
Fixed by moving the data pointer to a register `mul32` never touches.
See `CHANGELOG.md`'s Phase 11 entry and `cpu_dot_bench.s`'s own header
comment for the full account -- documented rather than quietly
corrected, per this project's practice throughout.

### Completion detection: a GPIO sentinel, not a guessed cycle count

Phase 7's benchmarks (`sum_loop.s`, `array_sum.s`) used a hand-picked
snapshot cycle, verified once by simulation to be exactly when that
one short program finished. That approach doesn't scale to six
programs of different lengths and structures: hardcoding a wrong
snapshot cycle for even one of them would silently make the CPU-vs-
accelerator comparison unfair (measuring one program's real completion
against another's idle-loop padding).

Instead, every Phase 11 benchmark program writes a fixed sentinel
(`0xDEADBEEF`) to `GPIO_OUT` the instant its measured work is done,
then enters its halt loop.
`sim/testbenches/tb_benchmark_soc.sv` watches `GPIO_OUT` and records
the performance counters at the exact cycle the sentinel appears --
removing an entire class of human error (mis-hardcoded cycle counts),
consistent with this project's repeated "trust the simulator, not hand
math" lesson (see `CHANGELOG.md`'s Phase 5/7 entries for earlier
instances of that exact lesson).

### Verification, in the right order

1. **`mul32` verified in isolation** (`sim/programs/benchmarks/mul32_test.s`,
   both the single-cycle and pipelined CPU) -- before any kernel
   depends on it.
2. **CPU-only kernels verified at their actual benchmark size**
   (`sim/testbenches/tb_bench_cpu_correctness.sv`, `make
   test_bench_correctness`) against expected values computed in
   Python, not by hand -- this is what caught the `x1`/`ra` bug above.
3. **Accelerator-driven kernels** reuse the exact hardware/driver path
   already verified in Phase 9/10 (`tb_accelerator.sv`,
   `tb_soc_accel_custom.sv`) at a smaller N; running the same verified
   code at a larger N is the same "verify once, trust as benchmark
   thereafter" convention Phase 7 established for `sum_loop.s`/
   `array_sum.s`.
4. Only once all of the above passed was
   `scripts/run_benchmarks_accel.py` run to produce
   `results/accelerator_benchmark_report.md`.

## Results

See `results/accelerator_benchmark_report.md` for the full, generated
report (including the full performance-counter breakdown for every
program). Summary, reproduced here from that generated file so this
document isn't a second, potentially-stale source of the same numbers
-- regenerate with `make benchmarks_accel` if these look out of date:

| Operation | Size | CPU-only cycles | Accelerator cycles | Speedup |
|---|---|---|---|---|
| vecadd | N=16 | 397 | 216 | 1.84x |
| dot | N=16 | 1086 | 216 | 5.03x |
| matmul | 4x4 (16 elements) | 3857 | 324 | 11.90x |

The pattern is exactly what the CPU/accelerator ISA gap predicts:
**vecadd** (pure addition, native to RV32I) shows the smallest speedup
-- the accelerator still wins, but only by helping with loop/memory
overhead, not by doing anything the CPU couldn't already do
efficiently. **dot** and especially **matmul** (multiplication-heavy,
and RV32I has no hardware multiplier) show dramatically larger
speedups, growing with `matmul`'s `O(N^3)` multiply count. This is
real, measured, and honestly reported -- not a favorable-workload
cherry-pick -- and is exactly the kind of data point Phase 13's AI
workload scheduler needs to learn to route work correctly (see
`docs/scheduler.md`, once it exists).

## Run it yourself

```
make test_bench_correctness   # verify the CPU-only kernels first
make benchmarks_accel          # then measure and write the report
```

## What Phase 11 does not do

- No physical FPGA/hardware measurement -- pure RTL simulation, as
  with every other phase. FPGA resource *estimation* (still not
  execution) is Phase 12's job.
- No sweep across multiple problem sizes -- each operation is measured
  at one representative size (chosen so all three kernels do a
  comparable ~16-element amount of work). A crossover analysis (at
  what size does the accelerator stop being worth the MMIO overhead)
  would be a natural extension but is out of this phase's scope.
- No mixed/heterogeneous workload scheduling -- that begins in Phase
  13 (the AI scheduler) and is exercised end-to-end starting Phase 16.
