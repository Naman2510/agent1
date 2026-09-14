# accel_vecadd_bench.s -- Phase 11 benchmark: accelerator-driven vector
# add, N=16, SAME operands as cpu_vecadd_bench.s (A[i]=i+1, B[i]=i+2)
# so the two are a direct, fair comparison. Uses the ACCEL.* custom
# instructions (Phase 10, docs/custom_extension.md) to drive
# rtl/accelerator/accelerator.sv -- already verified correct at a
# smaller N in sim/testbenches/tb_accelerator.sv and
# tb_soc_accel_custom.sv; this program reuses that same verified
# hardware/driver path at the benchmark's N, per the "verify once,
# trust as benchmark thereafter" convention docs/benchmarking.md
# documents.
#
# See cpu_vecadd_bench.s's header comment for the GPIO-sentinel
# completion convention this program shares.

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
    addi x5, x4, 1                  # A[i] = i+1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2                   # B[i] = i+2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, setup_loop

    sw   x9, 8(x1)                # LEN = 16
    accel.vecadd                    # start VECADD

wait_loop:
    accel.stat x6                     # x6 = STATUS
    andi x7, x6, 1                      # BUSY bit
    bne  x7, x0, wait_loop

    sw   x30, 0(x29)                # sentinel: work is done
done:
    j    done
