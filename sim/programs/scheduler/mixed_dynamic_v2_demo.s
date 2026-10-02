# mixed_dynamic_v2_demo.s -- Phase 16's 12-workload stream, runtime
# decision boundary extracted from scheduler/models/scheduler_tree_v2.pkl
# by scheduler/runtime/gen_dynamic_v2_demo.py.

    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

# -- block w0: vecadd N=1 (runtime-computed decision) --
    li   x24, 1
    li   x25, 0
    li   x26, 1
    blt  x26, x24, w0_accel
    bne  x25, x0, w0_accel
    j    w0_cpu
w0_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3000
    li   x9, 1

    li   x4, 0
w0c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w0c_setup_loop

    li   x4, 0
w0c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w0c_compute_loop
    j    w0_done
w0_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 1
    li   x4, 0
w0a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w0a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

w0a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w0a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3000
    lw   x25, 0(x24)
    sw   x25, 0(x26)
w0_done:

# -- block w1: vecadd N=2 (runtime-computed decision) --
    li   x24, 2
    li   x25, 0
    li   x26, 1
    blt  x26, x24, w1_accel
    bne  x25, x0, w1_accel
    j    w1_cpu
w1_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3100
    li   x9, 2

    li   x4, 0
w1c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w1c_setup_loop

    li   x4, 0
w1c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w1c_compute_loop
    j    w1_done
w1_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2
    li   x4, 0
w1a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w1a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

w1a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w1a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3100
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
w1_done:

# -- block w2: dot N=4 (runtime-computed decision) --
    li   x24, 4
    li   x25, 4
    li   x26, 1
    blt  x26, x24, w2_accel
    bne  x25, x0, w2_accel
    j    w2_cpu
w2_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  4
    li   x20, 0

    li   x4, 0
w2c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w2c_setup_loop

    li   x4, 0
w2c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, w2c_compute_loop

    li   x27, 0x3200
    sw   x20, 0(x27)
    j    w2_done
w2_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
w2a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w2a_setup_loop

    sw   x9, 8(x1)
    accel.dot

w2a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w2a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3200
    sw   x25, 0(x26)
w2_done:

# -- block w3: matmul N=2 (runtime-computed decision) --
    li   x11, 2
    li   x12, 2
    jal  x1, mul32
    mv   x24, x10
    mv   x11, x24
    li   x12, 2
    jal  x1, mul32
    mv   x25, x10
    li   x26, 1
    blt  x26, x24, w3_accel
    bne  x25, x0, w3_accel
    j    w3_cpu
w3_cpu:
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3300
    li   x9, 2

    li   x13, 0
w3c_setup_i:
    li   x14, 0
w3c_setup_j:
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
    bne  x14, x9, w3c_setup_j
    addi x13, x13, 1
    bne  x13, x9, w3c_setup_i

    li   x13, 0
w3c_mm_i:
    li   x14, 0
w3c_mm_j:
    li   x19, 0
    li   x21, 0
w3c_mm_k:
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
    bne  x21, x9, w3c_mm_k

    slli x16, x13, 1
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, w3c_mm_j
    addi x13, x13, 1
    bne  x13, x9, w3c_mm_i
    j    w3_done
w3_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2

    li   x13, 0
w3a_setup_i:
    li   x14, 0
w3a_setup_j:
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
    bne  x14, x9, w3a_setup_j
    addi x13, x13, 1
    bne  x13, x9, w3a_setup_i

    sw   x9, 8(x1)
    accel.matmul

w3a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w3a_wait_loop

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
w3_done:

# -- block w4: vecadd N=4 (runtime-computed decision) --
    li   x24, 4
    li   x25, 0
    li   x26, 1
    blt  x26, x24, w4_accel
    bne  x25, x0, w4_accel
    j    w4_cpu
w4_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3400
    li   x9, 4

    li   x4, 0
w4c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w4c_setup_loop

    li   x4, 0
w4c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w4c_compute_loop
    j    w4_done
w4_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
w4a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w4a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

w4a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w4a_wait_loop

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
w4_done:

# -- block w5: dot N=8 (runtime-computed decision) --
    li   x24, 8
    li   x25, 8
    li   x26, 1
    blt  x26, x24, w5_accel
    bne  x25, x0, w5_accel
    j    w5_cpu
w5_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  8
    li   x20, 0

    li   x4, 0
w5c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w5c_setup_loop

    li   x4, 0
w5c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, w5c_compute_loop

    li   x27, 0x3500
    sw   x20, 0(x27)
    j    w5_done
w5_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 8
    li   x4, 0
w5a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w5a_setup_loop

    sw   x9, 8(x1)
    accel.dot

w5a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w5a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3500
    sw   x25, 0(x26)
w5_done:

# -- block w6: vecadd N=8 (runtime-computed decision) --
    li   x24, 8
    li   x25, 0
    li   x26, 1
    blt  x26, x24, w6_accel
    bne  x25, x0, w6_accel
    j    w6_cpu
w6_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3600
    li   x9, 8

    li   x4, 0
w6c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w6c_setup_loop

    li   x4, 0
w6c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w6c_compute_loop
    j    w6_done
w6_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 8
    li   x4, 0
w6a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w6a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

w6a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w6a_wait_loop

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
w6_done:

# -- block w7: matmul N=4 (runtime-computed decision) --
    li   x11, 4
    li   x12, 4
    jal  x1, mul32
    mv   x24, x10
    mv   x11, x24
    li   x12, 4
    jal  x1, mul32
    mv   x25, x10
    li   x26, 1
    blt  x26, x24, w7_accel
    bne  x25, x0, w7_accel
    j    w7_cpu
w7_cpu:
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3700
    li   x9, 4

    li   x13, 0
w7c_setup_i:
    li   x14, 0
w7c_setup_j:
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
    bne  x14, x9, w7c_setup_j
    addi x13, x13, 1
    bne  x13, x9, w7c_setup_i

    li   x13, 0
w7c_mm_i:
    li   x14, 0
w7c_mm_j:
    li   x19, 0
    li   x21, 0
w7c_mm_k:
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
    bne  x21, x9, w7c_mm_k

    slli x16, x13, 2
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, w7c_mm_j
    addi x13, x13, 1
    bne  x13, x9, w7c_mm_i
    j    w7_done
w7_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4

    li   x13, 0
w7a_setup_i:
    li   x14, 0
w7a_setup_j:
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
    bne  x14, x9, w7a_setup_j
    addi x13, x13, 1
    bne  x13, x9, w7a_setup_i

    sw   x9, 8(x1)
    accel.matmul

w7a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w7a_wait_loop

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
w7_done:

# -- block w8: dot N=16 (runtime-computed decision) --
    li   x24, 16
    li   x25, 16
    li   x26, 1
    blt  x26, x24, w8_accel
    bne  x25, x0, w8_accel
    j    w8_cpu
w8_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  16
    li   x20, 0

    li   x4, 0
w8c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w8c_setup_loop

    li   x4, 0
w8c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, w8c_compute_loop

    li   x27, 0x3800
    sw   x20, 0(x27)
    j    w8_done
w8_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 16
    li   x4, 0
w8a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w8a_setup_loop

    sw   x9, 8(x1)
    accel.dot

w8a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w8a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3800
    sw   x25, 0(x26)
w8_done:

# -- block w9: vecadd N=16 (runtime-computed decision) --
    li   x24, 16
    li   x25, 0
    li   x26, 1
    blt  x26, x24, w9_accel
    bne  x25, x0, w9_accel
    j    w9_cpu
w9_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3900
    li   x9, 16

    li   x4, 0
w9c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w9c_setup_loop

    li   x4, 0
w9c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w9c_compute_loop
    j    w9_done
w9_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 16
    li   x4, 0
w9a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w9a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

w9a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w9a_wait_loop

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
w9_done:

# -- block w10: dot N=32 (runtime-computed decision) --
    li   x24, 32
    li   x25, 32
    li   x26, 1
    blt  x26, x24, w10_accel
    bne  x25, x0, w10_accel
    j    w10_cpu
w10_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  32
    li   x20, 0

    li   x4, 0
w10c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w10c_setup_loop

    li   x4, 0
w10c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, w10c_compute_loop

    li   x27, 0x3a00
    sw   x20, 0(x27)
    j    w10_done
w10_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 32
    li   x4, 0
w10a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w10a_setup_loop

    sw   x9, 8(x1)
    accel.dot

w10a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w10a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3a00
    sw   x25, 0(x26)
w10_done:

# -- block w11: vecadd N=32 (runtime-computed decision) --
    li   x24, 32
    li   x25, 0
    li   x26, 1
    blt  x26, x24, w11_accel
    bne  x25, x0, w11_accel
    j    w11_cpu
w11_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3b00
    li   x9, 32

    li   x4, 0
w11c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w11c_setup_loop

    li   x4, 0
w11c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w11c_compute_loop
    j    w11_done
w11_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 32
    li   x4, 0
w11a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, w11a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

w11a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, w11a_wait_loop

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
w11_done:

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
