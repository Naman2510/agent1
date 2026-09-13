# Phase 3: Directed Instruction Tests

This document describes the automated test convention used to verify
every instruction in `docs/riscv.md` against the CPU built in Phase 2.

## Convention

Each directed test program lives under `sim/programs/tests/*.s` and is
self-checking:

- **x31 (`t6`) is the reserved result register.** No instruction under
  test may use x31 as an operand.
- On success, the program sets `x31 = 1` and parks in an infinite loop.
- On failure, the program sets `x31` to a distinct code of the form
  `0x8000_00xx` -- the low byte identifies *which* assertion inside the
  file failed -- and parks in an infinite loop.
- The generic testbench (`sim/testbenches/tb_directed_test.sv`) runs the
  program for a fixed number of cycles, then checks `x31 == 1`. It also
  tracks whether the control unit's `illegal` flag was ever asserted
  during the run (it must never be, for a well-formed RV32I program) and
  fails the test if so, independent of what `x31` says.

This is the same style used by the reference `riscv-tests` suite (one
self-checking program per instruction/feature, a reserved
pass/fail register, `ecall`-free since this project has no trap
architecture yet -- see `docs/riscv.md` section 4).

## Why one file covers several related instructions

Rather than one file per instruction (which would mean ~31 near-identical
tiny files), tests are grouped by category (all R-type arithmetic
together, all branches together, etc.) with **one assertion per
instruction inside the file**, each with its own distinct failure code.
This keeps the number of files manageable while keeping per-instruction
failure attribution exact: a failing test immediately names both the file
and the specific `x31` code, which maps 1:1 to one `bne ..., failN`
assertion in that file's source (see the comments in each `.s` file).

## Test files and what each verifies

| File | Instructions | Also covers |
|---|---|---|
| `tests/rtype_arith.s` | ADD, SUB, AND, OR, XOR | register dependencies (chained results) |
| `tests/rtype_shift_cmp.s` | SLL, SRL, SRA, SLT, SLTU | negative numbers, signed vs. unsigned comparison |
| `tests/itype_arith.s` | ADDI, SLTI, SLTIU, XORI, ORI, ANDI | negative immediates |
| `tests/itype_shift.s` | SLLI, SRLI, SRAI | arithmetic shift of a negative number |
| `tests/load_store.s` | LW, SW | register-dependency address calculation |
| `tests/branches.s` | BEQ, BNE, BLT, BGE, BLTU, BGEU | signed vs. unsigned branch semantics |
| `tests/upper_imm.s` | LUI, AUIPC | — |
| `tests/jumps.s` | JAL, JALR | return-address register dependency |
| `tests/zero_register.s` | (uses ADDI/ADD) | x0 hard-wired-zero on read *and* write |

Every instruction listed in `docs/riscv.md` section 3 has at least one
directed assertion in exactly one of these files. The task's required
coverage categories (arithmetic, logical, immediate operations, loads,
stores, branches, jumps, register dependencies, negative numbers, signed
comparisons, zero-register behavior) are each covered by at least one
file above, noted in the "Also covers" column.

## Running the suite

```bash
make test_isa
# or directly:
python3 scripts/run_directed_tests.py
```

The runner assembles every `.s` file under `sim/programs/tests/`,
compiles `tb_directed_test.sv` against the CPU **once**, then re-runs
that single compiled binary once per test with a `+HEXFILE=...
+TESTNAME=...` plusarg pair, and reports a pass/fail summary. It exits
non-zero if any test fails, so it is CI-friendly. Like Phase 2, it runs
under both Icarus Verilog and Verilator.
