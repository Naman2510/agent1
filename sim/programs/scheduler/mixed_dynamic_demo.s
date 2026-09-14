# mixed_dynamic_demo.s -- Phase 16: 12-workload mixed
# heterogeneous stream, engine chosen at RUNTIME per
# workload -- see scheduler/runtime/gen_mixed_workload_demo.py
# and docs/mixed_workloads.md.

    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

# -- block m0: vecadd N=1 (runtime-computed decision) --
    li   x24, 1
    li   x25, 0
    li   x26, 2
    blt  x26, x24, m0_accel
    bne  x25, x0, m0_accel
    j    m0_cpu
m0_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3000
    li   x9, 1

    li   x4, 0
m0c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m0c_setup_loop

    li   x4, 0
m0c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m0c_compute_loop
    j    m0_done
m0_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 1
    li   x4, 0
m0a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m0a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m0a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m0a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3000
    lw   x25, 0(x24)
    sw   x25, 0(x26)
m0_done:

# -- block m1: vecadd N=2 (runtime-computed decision) --
    li   x24, 2
    li   x25, 0
    li   x26, 2
    blt  x26, x24, m1_accel
    bne  x25, x0, m1_accel
    j    m1_cpu
m1_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3100
    li   x9, 2

    li   x4, 0
m1c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m1c_setup_loop

    li   x4, 0
m1c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m1c_compute_loop
    j    m1_done
m1_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2
    li   x4, 0
m1a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m1a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m1a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m1a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3100
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
m1_done:

# -- block m2: dot N=4 (runtime-computed decision) --
    li   x24, 4
    li   x25, 4
    li   x26, 2
    blt  x26, x24, m2_accel
    bne  x25, x0, m2_accel
    j    m2_cpu
m2_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  4
    li   x20, 0

    li   x4, 0
m2c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m2c_setup_loop

    li   x4, 0
m2c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m2c_compute_loop

    li   x27, 0x3200
    sw   x20, 0(x27)
    j    m2_done
m2_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
m2a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m2a_setup_loop

    sw   x9, 8(x1)
    accel.dot

m2a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m2a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3200
    sw   x25, 0(x26)
m2_done:

# -- block m3: matmul N=2 (runtime-computed decision) --
    li   x11, 2
    li   x12, 2
    jal  x1, mul32
    mv   x24, x10
    mv   x11, x24
    li   x12, 2
    jal  x1, mul32
    mv   x25, x10
    li   x26, 2
    blt  x26, x24, m3_accel
    bne  x25, x0, m3_accel
    j    m3_cpu
m3_cpu:
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3300
    li   x9, 2

    li   x13, 0
m3c_setup_i:
    li   x14, 0
m3c_setup_j:
    add  x15, x13, x14
    slli x16, x13, 1
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x23, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m3c_setup_j
    addi x13, x13, 1
    bne  x13, x9, m3c_setup_i

    li   x13, 0
m3c_mm_i:
    li   x14, 0
m3c_mm_j:
    li   x19, 0
    li   x21, 0
m3c_mm_k:
    slli x16, x13, 1
    add  x16, x16, x21
    slli x16, x16, 2
    add  x18, x23, x16
    lw   x11, 0(x18)

    slli x16, x21, 1
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x2, x16
    lw   x12, 0(x18)

    jal  x1, mul32
    add  x19, x19, x10

    addi x21, x21, 1
    bne  x21, x9, m3c_mm_k

    slli x16, x13, 1
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m3c_mm_j
    addi x13, x13, 1
    bne  x13, x9, m3c_mm_i
    j    m3_done
m3_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2

    li   x13, 0
m3a_setup_i:
    li   x14, 0
m3a_setup_j:
    add  x15, x13, x14
    slli x16, x13, 1
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x3, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m3a_setup_j
    addi x13, x13, 1
    bne  x13, x9, m3a_setup_i

    sw   x9, 8(x1)
    accel.matmul

m3a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m3a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3300
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
m3_done:

# -- block m4: vecadd N=4 (runtime-computed decision) --
    li   x24, 4
    li   x25, 0
    li   x26, 2
    blt  x26, x24, m4_accel
    bne  x25, x0, m4_accel
    j    m4_cpu
m4_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3400
    li   x9, 4

    li   x4, 0
m4c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m4c_setup_loop

    li   x4, 0
m4c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m4c_compute_loop
    j    m4_done
m4_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
m4a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m4a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m4a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m4a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3400
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
m4_done:

# -- block m5: dot N=8 (runtime-computed decision) --
    li   x24, 8
    li   x25, 8
    li   x26, 2
    blt  x26, x24, m5_accel
    bne  x25, x0, m5_accel
    j    m5_cpu
m5_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  8
    li   x20, 0

    li   x4, 0
m5c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m5c_setup_loop

    li   x4, 0
m5c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m5c_compute_loop

    li   x27, 0x3500
    sw   x20, 0(x27)
    j    m5_done
m5_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 8
    li   x4, 0
m5a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m5a_setup_loop

    sw   x9, 8(x1)
    accel.dot

m5a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m5a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3500
    sw   x25, 0(x26)
m5_done:

# -- block m6: vecadd N=8 (runtime-computed decision) --
    li   x24, 8
    li   x25, 0
    li   x26, 2
    blt  x26, x24, m6_accel
    bne  x25, x0, m6_accel
    j    m6_cpu
m6_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3600
    li   x9, 8

    li   x4, 0
m6c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m6c_setup_loop

    li   x4, 0
m6c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m6c_compute_loop
    j    m6_done
m6_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 8
    li   x4, 0
m6a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m6a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m6a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m6a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3600
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
    lw   x25, 16(x24)
    sw   x25, 16(x26)
    lw   x25, 20(x24)
    sw   x25, 20(x26)
    lw   x25, 24(x24)
    sw   x25, 24(x26)
    lw   x25, 28(x24)
    sw   x25, 28(x26)
m6_done:

# -- block m7: matmul N=4 (runtime-computed decision) --
    li   x11, 4
    li   x12, 4
    jal  x1, mul32
    mv   x24, x10
    mv   x11, x24
    li   x12, 4
    jal  x1, mul32
    mv   x25, x10
    li   x26, 2
    blt  x26, x24, m7_accel
    bne  x25, x0, m7_accel
    j    m7_cpu
m7_cpu:
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3700
    li   x9, 4

    li   x13, 0
m7c_setup_i:
    li   x14, 0
m7c_setup_j:
    add  x15, x13, x14
    slli x16, x13, 2
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x23, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m7c_setup_j
    addi x13, x13, 1
    bne  x13, x9, m7c_setup_i

    li   x13, 0
m7c_mm_i:
    li   x14, 0
m7c_mm_j:
    li   x19, 0
    li   x21, 0
m7c_mm_k:
    slli x16, x13, 2
    add  x16, x16, x21
    slli x16, x16, 2
    add  x18, x23, x16
    lw   x11, 0(x18)

    slli x16, x21, 2
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x2, x16
    lw   x12, 0(x18)

    jal  x1, mul32
    add  x19, x19, x10

    addi x21, x21, 1
    bne  x21, x9, m7c_mm_k

    slli x16, x13, 2
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m7c_mm_j
    addi x13, x13, 1
    bne  x13, x9, m7c_mm_i
    j    m7_done
m7_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4

    li   x13, 0
m7a_setup_i:
    li   x14, 0
m7a_setup_j:
    add  x15, x13, x14
    slli x16, x13, 2
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x3, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m7a_setup_j
    addi x13, x13, 1
    bne  x13, x9, m7a_setup_i

    sw   x9, 8(x1)
    accel.matmul

m7a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m7a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3700
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
    lw   x25, 16(x24)
    sw   x25, 16(x26)
    lw   x25, 20(x24)
    sw   x25, 20(x26)
    lw   x25, 24(x24)
    sw   x25, 24(x26)
    lw   x25, 28(x24)
    sw   x25, 28(x26)
    lw   x25, 32(x24)
    sw   x25, 32(x26)
    lw   x25, 36(x24)
    sw   x25, 36(x26)
    lw   x25, 40(x24)
    sw   x25, 40(x26)
    lw   x25, 44(x24)
    sw   x25, 44(x26)
    lw   x25, 48(x24)
    sw   x25, 48(x26)
    lw   x25, 52(x24)
    sw   x25, 52(x26)
    lw   x25, 56(x24)
    sw   x25, 56(x26)
    lw   x25, 60(x24)
    sw   x25, 60(x26)
m7_done:

# -- block m8: dot N=16 (runtime-computed decision) --
    li   x24, 16
    li   x25, 16
    li   x26, 2
    blt  x26, x24, m8_accel
    bne  x25, x0, m8_accel
    j    m8_cpu
m8_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  16
    li   x20, 0

    li   x4, 0
m8c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m8c_setup_loop

    li   x4, 0
m8c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m8c_compute_loop

    li   x27, 0x3800
    sw   x20, 0(x27)
    j    m8_done
m8_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 16
    li   x4, 0
m8a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m8a_setup_loop

    sw   x9, 8(x1)
    accel.dot

m8a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m8a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3800
    sw   x25, 0(x26)
m8_done:

# -- block m9: vecadd N=16 (runtime-computed decision) --
    li   x24, 16
    li   x25, 0
    li   x26, 2
    blt  x26, x24, m9_accel
    bne  x25, x0, m9_accel
    j    m9_cpu
m9_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3900
    li   x9, 16

    li   x4, 0
m9c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m9c_setup_loop

    li   x4, 0
m9c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m9c_compute_loop
    j    m9_done
m9_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 16
    li   x4, 0
m9a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m9a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m9a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m9a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3900
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
    lw   x25, 16(x24)
    sw   x25, 16(x26)
    lw   x25, 20(x24)
    sw   x25, 20(x26)
    lw   x25, 24(x24)
    sw   x25, 24(x26)
    lw   x25, 28(x24)
    sw   x25, 28(x26)
    lw   x25, 32(x24)
    sw   x25, 32(x26)
    lw   x25, 36(x24)
    sw   x25, 36(x26)
    lw   x25, 40(x24)
    sw   x25, 40(x26)
    lw   x25, 44(x24)
    sw   x25, 44(x26)
    lw   x25, 48(x24)
    sw   x25, 48(x26)
    lw   x25, 52(x24)
    sw   x25, 52(x26)
    lw   x25, 56(x24)
    sw   x25, 56(x26)
    lw   x25, 60(x24)
    sw   x25, 60(x26)
m9_done:

# -- block m10: dot N=32 (runtime-computed decision) --
    li   x24, 32
    li   x25, 32
    li   x26, 2
    blt  x26, x24, m10_accel
    bne  x25, x0, m10_accel
    j    m10_cpu
m10_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  32
    li   x20, 0

    li   x4, 0
m10c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m10c_setup_loop

    li   x4, 0
m10c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m10c_compute_loop

    li   x27, 0x3a00
    sw   x20, 0(x27)
    j    m10_done
m10_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 32
    li   x4, 0
m10a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m10a_setup_loop

    sw   x9, 8(x1)
    accel.dot

m10a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m10a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3a00
    sw   x25, 0(x26)
m10_done:

# -- block m11: vecadd N=32 (runtime-computed decision) --
    li   x24, 32
    li   x25, 0
    li   x26, 2
    blt  x26, x24, m11_accel
    bne  x25, x0, m11_accel
    j    m11_cpu
m11_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3b00
    li   x9, 32

    li   x4, 0
m11c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m11c_setup_loop

    li   x4, 0
m11c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m11c_compute_loop
    j    m11_done
m11_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 32
    li   x4, 0
m11a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m11a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m11a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m11a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3b00
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
    lw   x25, 16(x24)
    sw   x25, 16(x26)
    lw   x25, 20(x24)
    sw   x25, 20(x26)
    lw   x25, 24(x24)
    sw   x25, 24(x26)
    lw   x25, 28(x24)
    sw   x25, 28(x26)
    lw   x25, 32(x24)
    sw   x25, 32(x26)
    lw   x25, 36(x24)
    sw   x25, 36(x26)
    lw   x25, 40(x24)
    sw   x25, 40(x26)
    lw   x25, 44(x24)
    sw   x25, 44(x26)
    lw   x25, 48(x24)
    sw   x25, 48(x26)
    lw   x25, 52(x24)
    sw   x25, 52(x26)
    lw   x25, 56(x24)
    sw   x25, 56(x26)
    lw   x25, 60(x24)
    sw   x25, 60(x26)
    lw   x25, 64(x24)
    sw   x25, 64(x26)
    lw   x25, 68(x24)
    sw   x25, 68(x26)
    lw   x25, 72(x24)
    sw   x25, 72(x26)
    lw   x25, 76(x24)
    sw   x25, 76(x26)
    lw   x25, 80(x24)
    sw   x25, 80(x26)
    lw   x25, 84(x24)
    sw   x25, 84(x26)
    lw   x25, 88(x24)
    sw   x25, 88(x26)
    lw   x25, 92(x24)
    sw   x25, 92(x26)
    lw   x25, 96(x24)
    sw   x25, 96(x26)
    lw   x25, 100(x24)
    sw   x25, 100(x26)
    lw   x25, 104(x24)
    sw   x25, 104(x26)
    lw   x25, 108(x24)
    sw   x25, 108(x26)
    lw   x25, 112(x24)
    sw   x25, 112(x26)
    lw   x25, 116(x24)
    sw   x25, 116(x26)
    lw   x25, 120(x24)
    sw   x25, 120(x26)
    lw   x25, 124(x24)
    sw   x25, 124(x26)
m11_done:

    sw   x30, 0(x29)
done:
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
