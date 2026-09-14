# cpu_matmul_bench.s -- Phase 11 benchmark: CPU-only 4x4 matrix
# multiply (N=4, 16 elements per matrix -- the same total element
# count as cpu_vecadd_bench.s/cpu_dot_bench.s's N=16, so all three
# CPU-only kernels are doing a comparable amount of "real work" for a
# fair three-way comparison against their accelerator-driven
# counterparts), no hardware accelerator involved.
#
# A[i,j] = i+j+1, B[i,j] = i+j+2 (row-major, N=4), computed by a real
# nested setup loop. C = A*B via the standard triple-nested i/j/k loop,
# each term computed with the mul32 software multiply routine (see
# cpu_dot_bench.s's header comment for why RV32I needs one, and
# mul32_test.s for where it's verified). This is real O(N^3) work in
# software -- 64 software multiplies for N=4 -- expected to be the
# CPU-only kernel most dramatically slower than its accelerator
# counterpart, since rtl/accelerator/accelerator.sv's MATMUL does the
# same 64 multiply-accumulates with one hardware multiplier per cycle
# instead of a ~10-instruction shift-and-add loop per multiply.
#
# See cpu_vecadd_bench.s's header comment for the sentinel-completion
# convention and why there's no x31 self-check here.

    li   x23, 0x1000       # &A[0,0] (NOT x1 -- see cpu_dot_bench.s header comment)
    li   x2, 0x2000        # &B[0,0]
    li   x3, 0x3000        # &C[0,0]
    li   x9, 4                # N
    li   x29, 0x20000000     # GPIO base
    li   x30, 0xDEADBEEF      # sentinel value

    # ---- Setup: A[i,j] = i+j+1, B[i,j] = i+j+2, flattened row-major
    # (index = i*N+j) ----
    li   x13, 0               # i
setup_i:
    li   x14, 0                 # j
setup_j:
    add  x15, x13, x14            # i+j
    slli x16, x13, 2               # i*N (N=4 -> i<<2)
    add  x16, x16, x14              # i*N+j
    slli x16, x16, 2                # *4 for byte offset

    addi x17, x15, 1                 # A value = i+j+1
    add  x18, x23, x16
    sw   x17, 0(x18)

    addi x17, x15, 2                 # B value = i+j+2
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, setup_j
    addi x13, x13, 1
    bne  x13, x9, setup_i

    # ---- C[i,j] = sum_k A[i,k] * B[k,j] ----
    li   x13, 0               # i
mm_i:
    li   x14, 0                 # j
mm_j:
    li   x19, 0                   # acc (s3)
    li   x21, 0                    # k (s5)
mm_k:
    slli x16, x13, 2                 # i*N
    add  x16, x16, x21                 # i*N+k
    slli x16, x16, 2                   # *4
    add  x18, x23, x16
    lw   x11, 0(x18)                    # a1 = A[i,k]

    slli x16, x21, 2                     # k*N
    add  x16, x16, x14                    # k*N+j
    slli x16, x16, 2                      # *4
    add  x18, x2, x16
    lw   x12, 0(x18)                       # a2 = B[k,j]

    jal  x1, mul32                          # x10 = A[i,k]*B[k,j]
    add  x19, x19, x10

    addi x21, x21, 1
    bne  x21, x9, mm_k

    slli x16, x13, 2                          # i*N
    add  x16, x16, x14                          # i*N+j
    slli x16, x16, 2                             # *4
    add  x18, x3, x16
    sw   x19, 0(x18)                              # C[i,j] = acc

    addi x14, x14, 1
    bne  x14, x9, mm_j
    addi x13, x13, 1
    bne  x13, x9, mm_i

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
