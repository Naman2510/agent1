# accel_matmul_n8.s -- Phase 13 scheduler dataset: accelerator-driven
# 8x8 matrix multiply. Generated from
# sim/programs/benchmarks/accel_matmul_bench.s's structure (Phase 11);
# the loop bound N and the "i*N" address shift (3 = log2(8))
# both differ -- see gen_cpu_matmul()'s comment for why N is
# restricted to powers of two.

    li   x1, 0x30000000
    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 8

    li   x13, 0
setup_i:
    li   x14, 0
setup_j:
    add  x15, x13, x14
    slli x16, x13, 3
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x3, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, setup_j
    addi x13, x13, 1
    bne  x13, x9, setup_i

    sw   x9, 8(x1)
    accel.matmul

wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, wait_loop

    sw   x30, 0(x29)
done:
    j    done
