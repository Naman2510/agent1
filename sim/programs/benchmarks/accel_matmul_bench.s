# accel_matmul_bench.s -- Phase 11 benchmark: accelerator-driven 4x4
# matrix multiply (N=4), SAME operands as cpu_matmul_bench.s
# (A[i,j]=i+j+1, B[i,j]=i+j+2, row-major) for a direct, fair
# comparison. See accel_vecadd_bench.s's header comment for the
# driver/verification/sentinel conventions this program shares --
# rtl/accelerator/accelerator.sv's MATMUL was already verified correct
# at this same N=4 (non-symmetric operands) in
# sim/testbenches/tb_accelerator.sv and tb_soc_accel_custom.sv, so this
# benchmark reuses that exact verified path.

    li   x1, 0x30000000     # accelerator base
    li   x29, 0x20000000     # GPIO base
    li   x30, 0xDEADBEEF      # sentinel value

    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2            # &VECA[0,0]
    add  x3, x1, x3            # &VECB[0,0]

    li   x9, 4                   # N (matrix dimension)

    # ---- Setup: A[i,j] = i+j+1, B[i,j] = i+j+2, row-major (index = i*N+j) ----
    li   x13, 0                   # i
setup_i:
    li   x14, 0                     # j
setup_j:
    add  x15, x13, x14                # i+j
    slli x16, x13, 2                   # i*N (N=4 -> i<<2)
    add  x16, x16, x14                  # i*N+j
    slli x16, x16, 2                    # *4 for byte offset

    addi x17, x15, 1                     # A value = i+j+1
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x17, x15, 2                     # B value = i+j+2
    add  x18, x3, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, setup_j
    addi x13, x13, 1
    bne  x13, x9, setup_i

    sw   x9, 8(x1)                # LEN = 4
    accel.matmul                    # start MATMUL

wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, wait_loop

    sw   x30, 0(x29)
done:
    j    done
