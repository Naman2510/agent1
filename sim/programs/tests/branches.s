# branches.s -- Phase 3 directed test
# Covers: BEQ, BNE, BLT, BGE, BLTU, BGEU, a not-taken branch (must fall
# through), and the signed-vs-unsigned distinction for the same bit
# pattern.

    li   x1, 5
    li   x2, 5
    li   x3, 9

    beq  x1, x2, l1        # 5 == 5 -> taken
    j    fail1
l1:
    bne  x1, x3, l2        # 5 != 9 -> taken
    j    fail2
l2:
    li   x5, -1            # 0xFFFFFFFF
    li   x6, 1
    blt  x5, x6, l3        # signed:   -1 < 1              -> taken
    j    fail3
l3:
    bge  x6, x5, l4        # signed:    1 >= -1            -> taken
    j    fail4
l4:
    bltu x6, x5, l5        # unsigned:  1 < 0xFFFFFFFF     -> taken
    j    fail5
l5:
    bgeu x5, x6, l6        # unsigned:  0xFFFFFFFF >= 1    -> taken
    j    fail6
l6:
    # Not-taken branch: this must fall through to the next instruction,
    # not jump. If it were wrongly taken, x7 would jump straight to
    # fail7 without ever setting x7 = 1.
    beq  x1, x3, fail7     # 5 == 9 is false -> must NOT be taken
    li   x7, 1
    li   x4, 1
    bne  x7, x4, fail8

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
fail8:
    li x31, 0x80000008
    j done
test_pass:
    li x31, 1
done:
    j done
