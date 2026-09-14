# oracle_demo.s -- Phase 15 baseline: same 6-workload stream, every
# block forced to whichever engine Phase 13/14's real measured data
# says is actually faster for that exact workload -- the best any
# per-workload-static dispatcher could possibly do.

    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

# -- block blk0: vecadd N=1 (oracle: cpu, from real measured data) --
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3000
    li   x9, 1

    li   x4, 0
blk0_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk0_setup_loop

    li   x4, 0
blk0_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk0_compute_loop

# -- block blk1: vecadd N=2 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2
    li   x4, 0
blk1_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk1_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

blk1_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk1_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3080
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)

# -- block blk2: vecadd N=4 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
blk2_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk2_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

blk2_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk2_wait_loop

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

# -- block blk3: dot N=1 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 1
    li   x4, 0
blk3_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk3_setup_loop

    sw   x9, 8(x1)
    accel.dot

blk3_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk3_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3180
    sw   x25, 0(x26)

# -- block blk4: dot N=4 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
blk4_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, blk4_setup_loop

    sw   x9, 8(x1)
    accel.dot

blk4_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk4_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3200
    sw   x25, 0(x26)

# -- block blk5: matmul N=2 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2

    li   x13, 0
blk5_setup_i:
    li   x14, 0
blk5_setup_j:
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
    bne  x14, x9, blk5_setup_j
    addi x13, x13, 1
    bne  x13, x9, blk5_setup_i

    sw   x9, 8(x1)
    accel.matmul

blk5_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, blk5_wait_loop

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
