# cpu_matmul_n1.s -- Phase 13 scheduler dataset: CPU-only 1x1
# matrix multiply. Generated from
# sim/programs/benchmarks/cpu_matmul_bench.s's structure (Phase 11);
# the loop bound N and the "i*N"/"k*N" address shift (0 =
# log2(1)) both differ -- see this generator script's own header
# comment for why N is restricted to powers of two here (keeps the
# multiply-by-N in address computation a single `slli`, matching
# Phase 11's real, already-verified hardware timing, rather than
# introducing a software multiply that would change what's measured).

    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3000
    li   x9, 1
    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

    li   x13, 0
setup_i:
    li   x14, 0
setup_j:
    add  x15, x13, x14
    slli x16, x13, 0
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x23, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, setup_j
    addi x13, x13, 1
    bne  x13, x9, setup_i

    li   x13, 0
mm_i:
    li   x14, 0
mm_j:
    li   x19, 0
    li   x21, 0
mm_k:
    slli x16, x13, 0
    add  x16, x16, x21
    slli x16, x16, 2
    add  x18, x23, x16
    lw   x11, 0(x18)

    slli x16, x21, 0
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x2, x16
    lw   x12, 0(x18)

    jal  x1, mul32
    add  x19, x19, x10

    addi x21, x21, 1
    bne  x21, x9, mm_k

    slli x16, x13, 0
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, mm_j
    addi x13, x13, 1
    bne  x13, x9, mm_i

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
