# Benchmark Baseline (Framework Phase 1, 2026-10-03)

The numbers every later framework phase must preserve. All are **simulated cycle
counts** (Icarus Verilog 12.0 performance counters on `rtl/cpu/riscv_soc.sv`;
correctness additionally on Verilator 5.020). They are not physical-hardware latency,
throughput or energy figures.

## How this baseline was established

- Commit `a938891`, clean tree. `make demo` (all phases + post-v1 stages, synthesis
  skipped by default): **exit 0, ALL STEPS COMPLETED, zero failure markers, 6 min 40 s**
  wall time on this container.
- The co-scheduler stage regenerated every program, profile and `results.json`
  **byte-identical** to the committed files; every `results/*.md` was unchanged
  apart from its "Generated" timestamp. This was the second independent full regression of
  this commit's content today; both gave identical counts.

## Co-scheduler results (`results/coschedule_report.md`)

| Stream | Core | Always accel | Serial oracle | Co-schedule | Predicted | Gain vs. oracle |
|---|---|---:|---:|---:|---:|---:|
| phase15 (6 tasks) | rv32i | 389 | 379 | 365 | 371 | 3.7% |
| phase15 | mul | 389 | 374 | 356 | 364 | 4.8% |
| phase16 (12 tasks) | rv32i | 2,366 | 2,356 | 2,262 | 2,264 | 4.0% |
| phase16 | mul | 2,366 | 2,356 | 2,262 | 2,264 | 4.0% |
| full24 (24 tasks) | rv32i | 6,592 | 6,582 | 6,072 | 6,071 | 7.75% |
| full24 | mul | 6,592 | 6,577 | 6,004 | 6,011 | 8.71% |

Serial programs (always-accel, oracle): predicted = measured exactly (12/12).
Exhaustive optimum on phase15 (model cycles): rv32i 371, mul 364, equal to the planner.
Scorecard: 100/100 (`results/coschedule_scorecard.md`). Correctness: 18 programs, 2,058
output words, Icarus + Verilator.

## Per-task profile (cycles beyond the 8-cycle empty program)

`cpu` = one-task program on the CPU; `acc` = on the accelerator, serially;
`busy` = accelerator BUSY interval. Operands are the synthetic pattern (small positive
integers), which matters for `mul32`'s data-dependent latency (TECHNICAL_DEBT D8).

| Op | N | rv32i cpu | rv32i acc | rv32i busy | mul cpu | mul acc | mul busy |
|---|---:|---:|---:|---:|---:|---:|---:|
| vecadd | 1 | 29 | 39 | 1 | 29 | 39 | 1 |
| vecadd | 2 | 53 | 53 | 2 | 53 | 53 | 2 |
| vecadd | 3 | 77 | 67 | 3 | 77 | 67 | 3 |
| vecadd | 4 | 101 | 81 | 4 | 101 | 81 | 4 |
| vecadd | 6 | 149 | 109 | 6 | 149 | 109 | 6 |
| vecadd | 8 | 197 | 143 | 8 | 197 | 143 | 8 |
| vecadd | 12 | 293 | 199 | 12 | 293 | 199 | 12 |
| vecadd | 16 | 389 | 261 | 16 | 389 | 261 | 16 |
| vecadd | 32 | 773 | 503 | 32 | 773 | 503 | 32 |
| vecadd | 64 | 1541 | 981 | 64 | 1541 | 981 | 64 |
| dot | 1 | 59 | 35 | 1 | 30 | 35 | 1 |
| dot | 2 | 110 | 46 | 2 | 53 | 46 | 2 |
| dot | 3 | 172 | 57 | 3 | 76 | 57 | 3 |
| dot | 4 | 233 | 68 | 4 | 99 | 68 | 4 |
| dot | 6 | 354 | 90 | 6 | 145 | 90 | 6 |
| dot | 8 | 497 | 118 | 8 | 191 | 118 | 8 |
| dot | 12 | 779 | 162 | 12 | 283 | 162 | 12 |
| dot | 16 | 1081 | 212 | 16 | 375 | 212 | 16 |
| dot | 32 | 2381 | 406 | 32 | 743 | 406 | 32 |
| dot | 64 | 5265 | 788 | 64 | 1479 | 788 | 64 |
| matmul | 1 | 80 | 45 | 1 | 51 | 45 | 1 |
| matmul | 2 | 493 | 105 | 8 | 245 | 105 | 8 |
| matmul | 4 | 3849 | 369 | 64 | 1485 | 369 | 64 |
| matmul | 8 | 32877 | 1647 | 512 | 10229 | 1647 | 512 |

## Golden files (SHA-256, first 16 hex digits)

`tests/test_framework_equivalence.py` regenerates all of these from the committed
profiles and compares them byte for byte, so any behaviour change in program generation
fails a 5-second test before it reaches the simulator.

| File (`sim/programs/coschedule/`) | SHA-256 |
|---|---|
| `full24_mul_always_accel.s` | `7b80f9773113cd5d` |
| `full24_mul_cosched.s` | `69ec374b8f769703` |
| `full24_mul_oracle.s` | `a07755afcc9a4130` |
| `full24_rv32i_always_accel.s` | `a4fd60467c53c916` |
| `full24_rv32i_cosched.s` | `ebf208d9c97b6622` |
| `full24_rv32i_oracle.s` | `55f9d02134af8af9` |
| `phase15_mul_always_accel.s` | `d380c36eb366bd41` |
| `phase15_mul_cosched.s` | `0572fc1dfe22f93a` |
| `phase15_mul_oracle.s` | `685f284a92e29e06` |
| `phase15_rv32i_always_accel.s` | `81965dc4f6f34323` |
| `phase15_rv32i_cosched.s` | `b44eaf53ef156af2` |
| `phase15_rv32i_oracle.s` | `245ade039b656a0c` |
| `phase16_mul_always_accel.s` | `25dc982166dec499` |
| `phase16_mul_cosched.s` | `bd99edac3dd80239` |
| `phase16_mul_oracle.s` | `60f3954f46b48063` |
| `phase16_rv32i_always_accel.s` | `d50a78c8185b268b` |
| `phase16_rv32i_cosched.s` | `e5ca45f1dc0fa670` |
| `phase16_rv32i_oracle.s` | `68515e53a1f93960` |
| `full24.expect` | `9b63f7da7c7af94f` |
| `phase15.expect` | `a4cdc4203d0abee8` |
| `phase16.expect` | `dd934d15d801cc5e` |

## Reproduce

```
make demo              # full regression (includes `make coschedule`)
make coschedule        # co-scheduler stage only
make test_framework    # fast Python suite incl. the golden-file test (added in Phase 2)
```
