# mixed_always_cpu_demo.s -- Phase 16 baseline: same 12-workload
# stream, every block forced to the CPU-only path.

    li   x29, 0x20000000
    li   x30, 0xDEADBEEF

# -- block m0: vecadd N=1 (forced cpu) --
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

# -- block m1: vecadd N=2 (forced cpu) --
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3100
    li   x9, 2

    li   x4, 0
m1_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m1_setup_loop

    li   x4, 0
m1_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m1_compute_loop

# -- block m2: dot N=4 (forced cpu) --
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  4
    li   x20, 0

    li   x4, 0
m2_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m2_setup_loop

    li   x4, 0
m2_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m2_compute_loop

    li   x27, 0x3200
    sw   x20, 0(x27)

# -- block m3: matmul N=2 (forced cpu) --
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3300
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
    add  x18, x23, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m3_setup_j
    addi x13, x13, 1
    bne  x13, x9, m3_setup_i

    li   x13, 0
m3_mm_i:
    li   x14, 0
m3_mm_j:
    li   x19, 0
    li   x21, 0
m3_mm_k:
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
    bne  x21, x9, m3_mm_k

    slli x16, x13, 1
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m3_mm_j
    addi x13, x13, 1
    bne  x13, x9, m3_mm_i

# -- block m4: vecadd N=4 (forced cpu) --
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3400
    li   x9, 4

    li   x4, 0
m4_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m4_setup_loop

    li   x4, 0
m4_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m4_compute_loop

# -- block m5: dot N=8 (forced cpu) --
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  8
    li   x20, 0

    li   x4, 0
m5_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m5_setup_loop

    li   x4, 0
m5_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m5_compute_loop

    li   x27, 0x3500
    sw   x20, 0(x27)

# -- block m6: vecadd N=8 (forced cpu) --
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3600
    li   x9, 8

    li   x4, 0
m6_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m6_setup_loop

    li   x4, 0
m6_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m6_compute_loop

# -- block m7: matmul N=4 (forced cpu) --
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, 0x3700
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
    add  x18, x23, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m7_setup_j
    addi x13, x13, 1
    bne  x13, x9, m7_setup_i

    li   x13, 0
m7_mm_i:
    li   x14, 0
m7_mm_j:
    li   x19, 0
    li   x21, 0
m7_mm_k:
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
    bne  x21, x9, m7_mm_k

    slli x16, x13, 2
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, m7_mm_j
    addi x13, x13, 1
    bne  x13, x9, m7_mm_i

# -- block m8: dot N=16 (forced cpu) --
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  16
    li   x20, 0

    li   x4, 0
m8_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m8_setup_loop

    li   x4, 0
m8_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m8_compute_loop

    li   x27, 0x3800
    sw   x20, 0(x27)

# -- block m9: vecadd N=16 (forced cpu) --
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3900
    li   x9, 16

    li   x4, 0
m9_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m9_setup_loop

    li   x4, 0
m9_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m9_compute_loop

# -- block m10: dot N=32 (forced cpu) --
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  32
    li   x20, 0

    li   x4, 0
m10_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m10_setup_loop

    li   x4, 0
m10_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, m10_compute_loop

    li   x27, 0x3a00
    sw   x20, 0(x27)

# -- block m11: vecadd N=32 (forced cpu) --
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, 0x3b00
    li   x9, 32

    li   x4, 0
m11_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m11_setup_loop

    li   x4, 0
m11_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, m11_compute_loop

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
