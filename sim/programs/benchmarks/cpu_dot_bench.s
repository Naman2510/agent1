# cpu_dot_bench.s -- Phase 11 benchmark: CPU-only dot product, N=16,
# no hardware accelerator involved. A[i] = i+1, B[i] = i+2 (same
# operands as cpu_vecadd_bench.s), result = sum_i A[i]*B[i].
#
# RV32I (this project's ISA subset) has no hardware multiplier, so
# each term is computed by the mul32 shift-and-add software multiply
# routine -- verified independently BEFORE this file was written, in
# sim/programs/benchmarks/mul32_test.s (see that file's header
# comment). This is expected to make CPU-only DOT substantially slower
# than the accelerator's hardware multiply-accumulate for the same
# operation -- that difference, measured honestly, is exactly the kind
# of real data point this project exists to produce (see
# docs/benchmarking.md), not something to work around or hide.
#
# See cpu_vecadd_bench.s's header comment for the sentinel-completion
# convention and why there's no x31 self-check here (correctness is
# established separately, by sim/testbenches/tb_bench_cpu_correctness.sv,
# at the actual benchmark size).
#
# Register note (a real bug this file had, caught by simulation, not
# assumed correct): x1 is the RISC-V ABI return-address register
# ("ra") -- `jal x1, mul32` overwrites it with the return address on
# every call. An earlier version of this file also used x1 to hold
# &A[0], which corrupted that base pointer after the FIRST loop
# iteration's call to mul32 (every subsequent A[i] load then read from
# an unrelated address), silently producing a wrong dot-product result
# that happened to equal exactly the first term. Fixed by moving &A[0]
# to x23 (s7), a register mul32 never touches -- see
# CHANGELOG.md's Phase 11 entry for the full account.

    li   x23, 0x1000        # &A[0] (NOT x1 -- see header comment)
    li   x2,  0x2000         # &B[0]
    li   x9,  16               # N
    li   x29, 0x20000000        # GPIO base
    li   x30, 0xDEADBEEF         # sentinel value
    li   x20, 0                    # running dot-product accumulator (s4;
                                     # avoids mul32's clobbered registers,
                                     # x5-x7/x10-x12 -- see mul32_test.s)

    li   x4, 0
setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, setup_loop

    li   x4, 0
compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)             # a1 = A[i]  (mul32's first operand)
    add  x7, x2, x6
    lw   x12, 0(x7)             # a2 = B[i]  (mul32's second operand)
    jal  x1, mul32                # x10 = A[i] * B[i]
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, compute_loop

    sw   x30, 0(x29)
    j    done

mul32:                      # x10 = x11 * x12  (see mul32_test.s)
    li   x10, 0
    mv   x5, x11
    mv   x6, x12
mul32_loop:
    beq  x6, x0, mul32_done
    andi x7, x6, 1
    beq  x7, x0, mul32_skip
    add  x10, x10, x5
mul32_skip:
    slli x5, x5, 1
    srli x6, x6, 1
    j    mul32_loop
mul32_done:
    ret

done:
    j done
