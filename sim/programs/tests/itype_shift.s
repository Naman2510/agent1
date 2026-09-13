# itype_shift.s -- Phase 3 directed test
# Covers: SLLI, SRLI, SRAI, plus an arithmetic shift of a negative number.

    li    x1, 1
    slli  x2, x1, 5        # 1 << 5 = 32
    li    x4, 32
    bne   x2, x4, fail1

    li    x3, -16          # 0xFFFFFFF0
    srli  x5, x3, 4        # logical shift:    0x0FFFFFFF
    li    x4, 0x0FFFFFFF
    bne   x5, x4, fail2

    srai  x6, x3, 4        # arithmetic shift: -16 >> 4 = -1 (0xFFFFFFFF)
    li    x4, -1
    bne   x6, x4, fail3

    j     test_pass
fail1:
    li x31, 0x80000001
    j done
fail2:
    li x31, 0x80000002
    j done
fail3:
    li x31, 0x80000003
    j done
test_pass:
    li x31, 1
done:
    j done
