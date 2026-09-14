# accel_custom_demo.s -- Phase 10 end-to-end test for the ACCEL.*
# custom RISC-V instructions (docs/custom_extension.md). This is the
# SAME three-operation sequence and SAME expected results as
# sim/programs/soc/accel_demo.s (Phase 9's plain-MMIO version) --
# deliberately, so the two programs are a direct before/after
# comparison of what the custom extension buys: every CTRL-register
# write (`li x5, 0b0NN1; sw x5, 0(x1)`, two instructions and a
# hand-encoded bit pattern) becomes one `accel.vecadd`/`accel.dot`/
# `accel.matmul` instruction with nothing to encode by hand, and every
# STATUS-register read (`lw x6, 4(x1)`, needing the offset constant)
# becomes `accel.stat x6`. LEN still has to be written via an ordinary
# `sw` -- the custom extension only replaces the fixed-address,
# fixed-data half of the driver sequence (see docs/custom_extension.md
# for why).

    li   x1, 0x30000000      # accelerator base (used below only for
                               # LEN/VECA/VECB/VECOUT/RESULT, which the
                               # custom extension does not replace)

    # ===================================================================
    # OP_VECADD: a=[1,2,3,4], b=[10,20,30,40] -> out=[11,22,33,44]
    # ===================================================================
    li   x2, 0x1000
    li   x3, 0x2000
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

    li   x5, 4
    sw   x5, 8(x1)             # LEN = 4
    accel.vecadd                # replaces: li x5,0b011; sw x5,0(x1)

vecadd_wait:
    accel.stat x6                # replaces: lw x6, 4(x1)
    andi x7, x6, 1
    bne  x7, x0, vecadd_wait
    andi x7, x6, 4
    bne  x7, x0, fail1

    li   x8, 0x3000
    add  x8, x1, x8
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
    # OP_DOT: same operands -> 1*10+2*20+3*30+4*40 = 300
    # ===================================================================
    li   x5, 4
    sw   x5, 8(x1)
    accel.dot                   # replaces: li x5,0b101; sw x5,0(x1)

dot_wait:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, dot_wait
    andi x7, x6, 4
    bne  x7, x0, fail3

    lw   x9, 12(x1)              # RESULT
    li   x10, 300
    bne  x9, x10, fail4

    # ===================================================================
    # OP_MATMUL: N=2, A=[1 2;3 4], B=[5 6;7 8] -> C=[19 22;43 50]
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

    li   x5, 2
    sw   x5, 8(x1)
    accel.matmul                # replaces: li x5,0b111; sw x5,0(x1)

matmul_wait:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, matmul_wait
    andi x7, x6, 4
    bne  x7, x0, fail5

    lw   x9, 0(x8)
    li   x10, 19
    bne  x9, x10, fail6
    lw   x9, 4(x8)
    li   x10, 22
    bne  x9, x10, fail6
    lw   x9, 8(x8)
    li   x10, 43
    bne  x9, x10, fail6
    lw   x9, 12(x8)
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
