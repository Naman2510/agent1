# accel_dot_bench.s -- Phase 11 benchmark: accelerator-driven dot
# product, N=16, SAME operands as cpu_dot_bench.s (A[i]=i+1, B[i]=i+2)
# for a direct, fair comparison -- this is the operation where the
# accelerator's single-cycle-per-term hardware multiply-accumulate is
# expected to contrast most sharply against the CPU-only kernel's
# ~10-instruction software shift-and-add multiply per term (see
# cpu_dot_bench.s's header comment). See accel_vecadd_bench.s's header
# comment for the driver/verification/sentinel conventions this
# program shares.

    li   x1, 0x30000000     # accelerator base
    li   x29, 0x20000000     # GPIO base
    li   x30, 0xDEADBEEF      # sentinel value

    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2            # &VECA[0]
    add  x3, x1, x3            # &VECB[0]

    li   x9, 16                  # N
    li   x4, 0                    # i
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

    sw   x9, 8(x1)                # LEN = 16
    accel.dot                       # start DOT

wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, wait_loop

    sw   x30, 0(x29)
done:
    j    done
