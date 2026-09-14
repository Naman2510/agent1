# Performance Report (Phase 7)

Generated 2026-09-14 07:53 UTC by `scripts/run_benchmarks.py` from actual Icarus Verilog simulation of `rtl/cpu/riscv_cpu_pipeline.sv`. Every number below comes directly from that simulation's performance counters (`rtl/cpu/perf_counters.sv`) -- none are estimated or hand-computed. Each program's correctness (the actual computed result, not just its timing) is separately verified by `sim/testbenches/tb_perf_counters.sv` (`make test_perf`), which this report does not re-derive.

| Benchmark | Cycles | Instructions retired | CPI | Stalls | Branches | Taken | Load-use stalls | Forwarding events | Flushes |
|---|---|---|---|---|---|---|---|---|---|
| sum_loop | 56 | 34 | 1.647 | 0 | 10 | 9 | 0 | 12 | 10 |
| array_sum | 51 | 34 | 1.500 | 5 | 5 | 4 | 5 | 17 | 5 |

## Notes

- `sum_loop`: a pure-ALU loop (sum 1..10) with no memory accesses -- zero load-use stalls, CPI close to 1 (ideal), with overhead from pipeline fill and the taken-branch flush on every loop iteration.
- `array_sum`: sums 5 memory-resident values with the loaded value used by the very next instruction every iteration -- a genuine load-use hazard each time, visible directly in the nonzero stall/load-use-stall columns, and a *lower* CPI than `sum_loop` despite the stalls, because this program is shorter and pays proportionally less pipeline-fill overhead relative to its instruction count.
- Flush counts are one higher than each program's real taken-branch count: flush is counted when EX resolves a redirect, 3 pipeline stages before that instruction retires, so each snapshot catches the halt loop's first `j done` having resolved in EX without yet reaching WB. See `sim/testbenches/tb_perf_counters.sv`'s header comment.
- CPI here is `cycles / instructions retired`, computed in this script, not in hardware -- see `rtl/cpu/perf_counters.sv`'s header comment for why.

