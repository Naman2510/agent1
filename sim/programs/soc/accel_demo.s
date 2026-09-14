# accel_demo.s -- Phase 9 end-to-end test: the CPU drives the hardware
# accelerator (rtl/accelerator/accelerator.sv) entirely through ordinary
# LW/SW instructions across the real SoC bus (0x30000000 base), exactly
# as a real driver would -- this is what proves the accelerator is
# actually reachable and controllable from software, not just correct
# in isolation (that unit-level correctness is
# sim/testbenches/tb_accelerator.sv's job).
#
# Exercises all three operations in the task's own vector-add ->
# dot-product -> matrix-multiply progression, each with a small,
# hand-computable input so the expected result can be checked with a
# plain BNE against a literal, same convention as every other directed
# test in this project (x31/t6 pass/fail, docs/testing.md).

    # ---- Register map (see rtl/accelerator/accelerator.sv header) ----
    li   x1, 0x30000000      # accelerator base
    # offsets: CTRL=0x0, STATUS=0x4, LEN=0x8, RESULT=0xC
    # VECA=0x1000, VECB=0x2000, VECOUT=0x3000

    # ===================================================================
    # OP_VECADD: a=[1,2,3,4], b=[10,20,30,40] -> out=[11,22,33,44]
    # ===================================================================
    li   x2, 0x1000           # VECA offset
    li   x3, 0x2000           # VECB offset
    add  x2, x1, x2           # &VECA[0]
    add  x3, x1, x3           # &VECB[0]

    li   x4, 1
    sw   x4, 0(x2)
    li   x4, 2
    sw   x4, 4(x2)
    li   x4, 3
    sw   x4, 8(x2)
    li   x4, 4
    sw   x4, 12(x2)

    li   x4, 10
    sw   x4, 0(x3)
    li   x4, 20
    sw   x4, 4(x3)
    li   x4, 30
    sw   x4, 8(x3)
    li   x4, 40
    sw   x4, 12(x3)

    li   x5, 4                # LEN = 4
    sw   x5, 8(x1)             # write LEN register
    li   x5, 0b011             # bits[2:1]=OP_VECADD(01), bit0=START
    sw   x5, 0(x1)             # write CTRL register -> starts VECADD

vecadd_wait:
    lw   x6, 4(x1)              # STATUS
    andi x7, x6, 1               # BUSY bit
    bne  x7, x0, vecadd_wait

    andi x7, x6, 4                # ERR bit
    bne  x7, x0, fail1

    li   x8, 0x3000
    add  x8, x1, x8            # &VECOUT[0]
    lw   x9, 0(x8)
    li   x10, 11
    bne  x9, x10, fail2
    lw   x9, 4(x8)
    li   x10, 22
    bne  x9, x10, fail2
    lw   x9, 8(x8)
    li   x10, 33
    bne  x9, x10, fail2
    lw   x9, 12(x8)
    li   x10, 44
    bne  x9, x10, fail2

    # ===================================================================
    # OP_DOT: a=[1,2,3,4], b=[10,20,30,40] (same operands, reused)
    # -> result = 1*10+2*20+3*30+4*40 = 10+40+90+160 = 300
    # ===================================================================
    li   x5, 4
    sw   x5, 8(x1)              # LEN = 4
    li   x5, 0b101              # bits[2:1]=OP_DOT(10), bit0=START
    sw   x5, 0(x1)

dot_wait:
    lw   x6, 4(x1)
    andi x7, x6, 1
    bne  x7, x0, dot_wait

    andi x7, x6, 4
    bne  x7, x0, fail3

    lw   x9, 12(x1)              # RESULT register
    li   x10, 300
    bne  x9, x10, fail4

    # ===================================================================
    # OP_MATMUL: N=2.
    #   A = [1 2; 3 4]   B = [5 6; 7 8]   (row-major)
    #   C = A*B = [1*5+2*7  1*6+2*8 ; 3*5+4*7  3*6+4*8]
    #           = [19 22 ; 43 50]
    # ===================================================================
    li   x4, 1
    sw   x4, 0(x2)
    li   x4, 2
    sw   x4, 4(x2)
    li   x4, 3
    sw   x4, 8(x2)
    li   x4, 4
    sw   x4, 12(x2)

    li   x4, 5
    sw   x4, 0(x3)
    li   x4, 6
    sw   x4, 4(x3)
    li   x4, 7
    sw   x4, 8(x3)
    li   x4, 8
    sw   x4, 12(x3)

    li   x5, 2                  # LEN = N = 2 (matrix dimension)
    sw   x5, 8(x1)
    li   x5, 0b111               # bits[2:1]=OP_MATMUL(11), bit0=START
    sw   x5, 0(x1)

matmul_wait:
    lw   x6, 4(x1)
    andi x7, x6, 1
    bne  x7, x0, matmul_wait

    andi x7, x6, 4
    bne  x7, x0, fail5

    lw   x9, 0(x8)                # VECOUT[0]
    li   x10, 19
    bne  x9, x10, fail6
    lw   x9, 4(x8)                # VECOUT[1]
    li   x10, 22
    bne  x9, x10, fail6
    lw   x9, 8(x8)                # VECOUT[2]
    li   x10, 43
    bne  x9, x10, fail6
    lw   x9, 12(x8)               # VECOUT[3]
    li   x10, 50
    bne  x9, x10, fail6

    j test_pass

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
