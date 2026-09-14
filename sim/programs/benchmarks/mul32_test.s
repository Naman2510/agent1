# mul32_test.s -- Phase 11 directed test for the software 32-bit
# multiply subroutine (shift-and-add) that Phase 11's CPU-only DOT and
# MATMUL benchmark kernels depend on. RV32I (this project's ISA
# subset) has no hardware multiplier -- the M extension isn't
# implemented -- so any CPU-side DOT/MATMUL benchmark needs a real,
# verified software multiply routine, not a hand-waved "and then it
# multiplies" comment. Verified here BEFORE it's used in any larger
# kernel, same "prove the primitive before building on it" discipline
# this project has followed since Phase 2's ALU.
#
# mul32: a0 (x10) = a1 (x11) * a2 (x12), unsigned 32-bit (low bits of
# the product only -- sufficient for every benchmark value in this
# project, all small positive integers). Standard shift-and-add
# multiplier: for each 1 bit of the multiplier (from LSB), add the
# (correspondingly left-shifted) multiplicand into the accumulator.
# Clobbers t0/t1/t2 (x5/x6/x7); uses ra (x1) as the return address, the
# same jal/jalr convention this project's own `ret` pseudo-op already
# relies on.

    li   x11, 6
    li   x12, 7
    jal  x1, mul32
    li   x13, 42
    bne  x10, x13, fail1

    li   x11, 0
    li   x12, 123
    jal  x1, mul32
    bne  x10, x0, fail2

    li   x11, 99
    li   x12, 0
    jal  x1, mul32
    bne  x10, x0, fail3

    li   x11, 15
    li   x12, 15
    jal  x1, mul32
    li   x13, 225
    bne  x10, x13, fail4

    li   x11, 1
    li   x12, 1000
    jal  x1, mul32
    li   x13, 1000
    bne  x10, x13, fail5

    li   x11, 256
    li   x12, 256
    jal  x1, mul32
    li   x13, 65536
    bne  x10, x13, fail6

    j    test_pass

mul32:                      # x10 = x11 * x12
    li   x10, 0              # result = 0
    mv   x5, x11              # t0 = working copy of multiplicand
    mv   x6, x12              # t1 = working copy of multiplier
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

fail1:
    li x31, 0x80000001
    j done
fail2:
    li x31, 0x80000002
    j done
fail3:
    li x31, 0x80000003
    j done
fail4:
    li x31, 0x80000004
    j done
fail5:
    li x31, 0x80000005
    j done
fail6:
    li x31, 0x80000006
    j done
test_pass:
    li x31, 1
done:
    j done
