# rtype_shift_cmp.s -- Phase 3 directed test
# Covers: SLL, SRL, SRA, SLT, SLTU, plus negative numbers and the
# signed-vs-unsigned comparison distinction (same bit pattern, opposite
# SLT/SLTU results).

    li   x1, 1
    li   x2, 4
    sll  x3, x1, x2        # 1 << 4 = 16
    li   x4, 16
    bne  x3, x4, fail1

    li   x5, -8            # 0xFFFFFFF8
    li   x6, 1
    srl  x7, x5, x6        # logical shift:    0x7FFFFFFC
    li   x4, 0x7FFFFFFC
    bne  x7, x4, fail2

    sra  x8, x5, x6        # arithmetic shift: -4 (0xFFFFFFFC)
    li   x4, -4
    bne  x8, x4, fail3

    slt  x9, x5, x1        # signed:   -8 < 1            -> 1
    li   x4, 1
    bne  x9, x4, fail4

    slt  x10, x1, x5       # signed:    1 < -8           -> 0
    li   x4, 0
    bne  x10, x4, fail5

    sltu x11, x5, x1       # unsigned: 0xFFFFFFF8 < 1    -> 0
    li   x4, 0
    bne  x11, x4, fail6

    sltu x12, x1, x5       # unsigned: 1 < 0xFFFFFFF8    -> 1
    li   x4, 1
    bne  x12, x4, fail7

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
fail7:
    li x31, 0x80000007
    j done
test_pass:
    li x31, 1
done:
    j done
