# accel_dot_n6.s -- Phase 13 scheduler dataset: accelerator-driven
# dot product, N=6. Generated from
# sim/programs/benchmarks/accel_dot_bench.s's structure (Phase 11);
# only the loop bound N differs.

    li   x1, 0x30000000
    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 6
    li   x4, 0
setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, setup_loop

    sw   x9, 8(x1)
    accel.dot

wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, wait_loop

    sw   x30, 0(x29)
done:
    j    done
