# cpu_dot_n32.s -- Phase 13 scheduler dataset: CPU-only dot product,
# N=32. Generated from sim/programs/benchmarks/cpu_dot_bench.s's
# structure (Phase 11); only the loop bound N differs. Uses the mul32
# software multiply routine (see mul32_test.s), and keeps &A[0] in
# x23, NOT x1, for the same real reason documented in
# cpu_dot_bench.s's header comment (x1 is jal's return-address
# register; a real bug from this exact mistake is in CHANGELOG.md's
# Phase 11 entry).

    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  32
    li   x29, 0x20000000
    li   x30, 0xDEADBEEF
    li   x20, 0

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
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, compute_loop

    sw   x30, 0(x29)
    j    done

mul32:
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
