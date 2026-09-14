# mixed_oracle_demo.s -- Phase 16 baseline: same 12-workload
# stream, every block forced to whichever engine Phase 13/14's
# real measured data says is actually faster.

    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

# -- block m0: vecadd N=1 (oracle: cpu, from real measured data) --
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3000
    li   x9, 1

    li   x4, 0
m0_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m0_setup_loop

    li   x4, 0
m0_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m0_compute_loop

# -- block m1: vecadd N=2 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2
    li   x4, 0
m1_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m1_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m1_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m1_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, 0x3100
    lw   x25, 0(x24)
    sw   x25, 0(x26)
    lw   x25, 4(x24)
    sw   x25, 4(x26)

# -- block m2: dot N=4 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
m2_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m2_setup_loop

    sw   x9, 8(x1)
    accel.dot

m2_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m2_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3200
    sw   x25, 0(x26)

# -- block m3: matmul N=2 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 2

    li   x13, 0
m3_setup_i:
    li   x14, 0
m3_setup_j:
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
    bne  x14, x9, m3_setup_j
    addi x13, x13, 1
    bne  x13, x9, m3_setup_i

    sw   x9, 8(x1)
    accel.matmul

m3_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m3_wait_loop

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

# -- block m4: vecadd N=4 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4
    li   x4, 0
m4_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m4_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m4_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m4_wait_loop

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

# -- block m5: dot N=8 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 8
    li   x4, 0
m5_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m5_setup_loop

    sw   x9, 8(x1)
    accel.dot

m5_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m5_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3500
    sw   x25, 0(x26)

# -- block m6: vecadd N=8 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 8
    li   x4, 0
m6_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m6_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m6_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m6_wait_loop

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

# -- block m7: matmul N=4 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 4

    li   x13, 0
m7_setup_i:
    li   x14, 0
m7_setup_j:
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
    bne  x14, x9, m7_setup_j
    addi x13, x13, 1
    bne  x13, x9, m7_setup_i

    sw   x9, 8(x1)
    accel.matmul

m7_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m7_wait_loop

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

# -- block m8: dot N=16 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 16
    li   x4, 0
m8_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m8_setup_loop

    sw   x9, 8(x1)
    accel.dot

m8_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m8_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3800
    sw   x25, 0(x26)

# -- block m9: vecadd N=16 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 16
    li   x4, 0
m9_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m9_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m9_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m9_wait_loop

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

# -- block m10: dot N=32 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 32
    li   x4, 0
m10_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m10_setup_loop

    sw   x9, 8(x1)
    accel.dot

m10_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m10_wait_loop

    lw   x25, 12(x1)
    li   x26, 0x3a00
    sw   x25, 0(x26)

# -- block m11: vecadd N=32 (oracle: accelerator, from real measured data) --
    li   x1, 805306368
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, 32
    li   x4, 0
m11_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m11_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

m11_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, m11_wait_loop

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
