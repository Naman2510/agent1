# rtype_arith.s -- Phase 3 directed test
# Covers: ADD, SUB, AND, OR, XOR, and register-dependency (chained results).
# See docs/testing.md for the pass/fail (x31) convention.

    li   x1, 12           # 0xC
    li   x2, 10           # 0xA

    add  x3, x1, x2       # 12+10 = 22
    li   x4, 22
    bne  x3, x4, fail1

    sub  x5, x1, x2       # 12-10 = 2
    li   x4, 2
    bne  x5, x4, fail2

    and  x6, x1, x2       # 0xC & 0xA = 0x8
    li   x4, 0x8
    bne  x6, x4, fail3

    or   x7, x1, x2       # 0xC | 0xA = 0xE
    li   x4, 0xE
    bne  x7, x4, fail4

    xor  x8, x1, x2       # 0xC ^ 0xA = 0x6
    li   x4, 0x6
    bne  x8, x4, fail5

    # Register dependency: each instruction consumes the result the
    # previous instruction just wrote back.
    add  x9, x3, x5       # 22+2 = 24
    add  x9, x9, x6       # 24+8 = 32
    li   x4, 32
    bne  x9, x4, fail6

    j    test_pass
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
