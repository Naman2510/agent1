# zero_register.s -- Phase 3 directed test
# Covers: x0 hard-wired-zero behavior, both as a read (always 0, used as
# an operand) and as a write target (must be silently discarded).

    li    x1, 123
    add   x2, x1, x0        # x0 as a source operand: 123 + 0 = 123
    li    x4, 123
    bne   x2, x4, fail1

    addi  x0, x1, 999       # attempt to write x0 -- must be discarded
    add   x3, x0, x0        # if the write "succeeded" this would not be 0
    li    x4, 0
    bne   x3, x4, fail2

    sub   x5, x0, x1        # x0 as a source operand in a subtraction:
                            # 0 - 123 = -123
    li    x4, -123
    bne   x5, x4, fail3

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
