# Accelerator Benchmark Report (Phase 11)

Generated 2026-09-17 16:40 UTC by `scripts/run_benchmarks_accel.py` from actual Icarus Verilog simulation of `rtl/cpu/riscv_soc.sv`. Every cycle count below comes directly from that simulation's performance counters (`rtl/cpu/perf_counters.sv`), read at the exact cycle each program signals completion via a GPIO sentinel write (see `sim/testbenches/tb_benchmark_soc.sv`'s header comment) -- none are estimated, hand-computed, or measured on physical hardware/FPGA. Speedup is `cycles(CPU-only) / cycles(accelerator-driven)`, computed here from those measured counts. CPU-only kernel correctness is verified separately by `sim/testbenches/tb_bench_cpu_correctness.sv` (`make test_bench_correctness`); accelerator-driven kernel correctness was already established in Phase 9/10 at smaller problem sizes.

| Operation | Size | CPU-only cycles | Accelerator cycles | Speedup |
|---|---|---|---|---|
| vecadd | N=16 | 397 | 216 | 1.84x |
| dot | N=16 | 1086 | 216 | 5.03x |
| matmul | 4x4 (16 elements) | 3857 | 324 | 11.90x |

## Full counter detail

| Program | Cycles | Instructions retired | Stalls | Branches | Taken | Load-use stalls | Forwarding events | Flushes |
|---|---|---|---|---|---|---|---|---|
| cpu_vecadd_bench | 397 | 317 | 16 | 32 | 30 | 16 | 200 | 31 |
| accel_vecadd_bench | 216 | 172 | 4 | 20 | 18 | 4 | 96 | 19 |
| cpu_dot_bench | 1086 | 762 | 0 | 164 | 70 | 0 | 241 | 161 |
| accel_dot_bench | 216 | 172 | 4 | 20 | 18 | 4 | 96 | 19 |
| cpu_matmul_bench | 3857 | 2809 | 0 | 536 | 210 | 0 | 1130 | 523 |
| accel_matmul_bench | 324 | 256 | 12 | 32 | 26 | 12 | 167 | 27 |

## Notes

- **vecadd**: the smallest speedup of the three, because RV32I natively executes `ADD` in one cycle -- the CPU-only kernel isn't fighting its ISA here, only paying ordinary loop/memory overhead the accelerator's MMIO setup (still done via CPU `SW`) pays a version of too.
- **dot** and **matmul**: RV32I (this project's ISA subset) has no hardware multiplier -- the CPU-only kernels compute every product with a real software shift-and-add multiply routine (`mul32`, verified in `sim/programs/benchmarks/mul32_test.s`), roughly 10 instructions per multiply versus the accelerator's one multiply-accumulate per cycle. **matmul** in particular does `N^3` multiplies in software (64 for N=4) against the accelerator's real sequential `N^3`-cycle hardware FSM (see `docs/accelerator.md`) -- the resulting large speedup is a direct, honest consequence of that ISA gap, not a favorable-workload cherry-pick.
- All three operations use IDENTICAL operands between their CPU-only and accelerator-driven versions (same `A[i]=i+1, B[i]=i+2` / `A[i,j]=i+j+1, B[i,j]=i+j+2` patterns), so the comparison is apples-to-apples -- see each program's own header comment.
- Every program (CPU-only and accelerator-driven alike) includes its own data-setup loop in the measured cycle count -- there is no hidden "warm cache" or pre-loaded-data assumption on either side.

