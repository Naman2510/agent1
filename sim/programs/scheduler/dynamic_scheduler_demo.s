# dynamic_scheduler_demo.s -- Phase 15: ONE program, 6 workloads,
# engine chosen at RUNTIME per workload by real RV32I instructions
# evaluating the trained scheduler's decision boundary -- see
# scheduler/runtime/gen_dynamic_scheduler_demo.py and
# docs/dynamic_scheduling.md.

    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

# -- block blk0: vecadd N=1 (runtime-computed decision) --
    li   x24, 1
    li   x25, 0
    li   x26, 2
    blt  x26, x24, blk0_accel
    bne  x25, x0, blk0_accel
    j    blk0_cpu
blk0_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3000
    li   x9, 1

    li   x4, 0
blk0c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk0c_setup_loop

    li   x4, 0
blk0c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk0c_compute_loop
    j    blk0_done
blk0_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 1
    li   x4, 0
blk0a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk0a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

blk0a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk0a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3000
    lw   x25, 0(x24)
    sw   x25, 0(x26)
blk0_done:

# -- block blk1: vecadd N=2 (runtime-computed decision) --
    li   x24, 2
    li   x25, 0
    li   x26, 2
    blt  x26, x24, blk1_accel
    bne  x25, x0, blk1_accel
    j    blk1_cpu
blk1_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3080
    li   x9, 2

    li   x4, 0
blk1c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk1c_setup_loop

    li   x4, 0
blk1c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk1c_compute_loop
    j    blk1_done
blk1_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2
    li   x4, 0
blk1a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk1a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

blk1a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk1a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3080
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
blk1_done:

# -- block blk2: vecadd N=4 (runtime-computed decision) --
    li   x24, 4
    li   x25, 0
    li   x26, 2
    blt  x26, x24, blk2_accel
    bne  x25, x0, blk2_accel
    j    blk2_cpu
blk2_cpu:
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3100
    li   x9, 4

    li   x4, 0
blk2c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk2c_setup_loop

    li   x4, 0
blk2c_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk2c_compute_loop
    j    blk2_done
blk2_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
blk2a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk2a_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

blk2a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk2a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3100
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
blk2_done:

# -- block blk3: dot N=1 (runtime-computed decision) --
    li   x24, 1
    li   x25, 1
    li   x26, 2
    blt  x26, x24, blk3_accel
    bne  x25, x0, blk3_accel
    j    blk3_cpu
blk3_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  1
    li   x20, 0

    li   x4, 0
blk3c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk3c_setup_loop

    li   x4, 0
blk3c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, blk3c_compute_loop

    li   x27, 0x3180
    sw   x20, 0(x27)
    j    blk3_done
blk3_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 1
    li   x4, 0
blk3a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk3a_setup_loop

    sw   x9, 8(x1)
    accel.dot

blk3a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk3a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3180
    sw   x25, 0(x26)
blk3_done:

# -- block blk4: dot N=4 (runtime-computed decision) --
    li   x24, 4
    li   x25, 4
    li   x26, 2
    blt  x26, x24, blk4_accel
    bne  x25, x0, blk4_accel
    j    blk4_cpu
blk4_cpu:
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  4
    li   x20, 0

    li   x4, 0
blk4c_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk4c_setup_loop

    li   x4, 0
blk4c_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, blk4c_compute_loop

    li   x27, 0x3200
    sw   x20, 0(x27)
    j    blk4_done
blk4_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
blk4a_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk4a_setup_loop

    sw   x9, 8(x1)
    accel.dot

blk4a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk4a_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3200
    sw   x25, 0(x26)
blk4_done:

# -- block blk5: matmul N=2 (runtime-computed decision) --
    li   x11, 2
    li   x12, 2
    jal  x1, mul32
    mv   x24, x10
    mv   x11, x24
    li   x12, 2
    jal  x1, mul32
    mv   x25, x10
    li   x26, 2
    blt  x26, x24, blk5_accel
    bne  x25, x0, blk5_accel
    j    blk5_cpu
blk5_cpu:
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3280
    li   x9, 2

    li   x13, 0
blk5c_setup_i:
    li   x14, 0
blk5c_setup_j:
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
    bne  x14, x9, blk5c_setup_j
    addi x13, x13, 1
    bne  x13, x9, blk5c_setup_i

    li   x13, 0
blk5c_mm_i:
    li   x14, 0
blk5c_mm_j:
    li   x19, 0
    li   x21, 0
blk5c_mm_k:
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
    bne  x21, x9, blk5c_mm_k

    slli x16, x13, 1
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, blk5c_mm_j
    addi x13, x13, 1
    bne  x13, x9, blk5c_mm_i
    j    blk5_done
blk5_accel:
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2

    li   x13, 0
blk5a_setup_i:
    li   x14, 0
blk5a_setup_j:
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
    bne  x14, x9, blk5a_setup_j
    addi x13, x13, 1
    bne  x13, x9, blk5a_setup_i

    sw   x9, 8(x1)
    accel.matmul

blk5a_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk5a_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3280
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)
    lw   x25, 8(x24)
    sw   x25, 8(x26)
    lw   x25, 12(x24)
    sw   x25, 12(x26)
blk5_done:

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
