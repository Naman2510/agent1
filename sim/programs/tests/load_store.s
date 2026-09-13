# load_store.s -- Phase 3 directed test
# Covers: LW, SW, plus a register-dependency address calculation (an
# address computed by one instruction is used as the base register of
# the very next instruction's memory access).

    li    x1, 100          # value 1
    li    x2, 200          # value 2
    li    x3, 64           # base address (word-aligned)

    sw    x1, 0(x3)        # mem[64] = 100
    sw    x2, 4(x3)        # mem[68] = 200

    lw    x5, 0(x3)
    li    x4, 100
    bne   x5, x4, fail1

    lw    x6, 4(x3)
    li    x4, 200
    bne   x6, x4, fail2

    # Register dependency: x7 is computed here and used as the base
    # register of the load on the very next instruction.
    addi  x7, x3, 4        # x7 = 64+4 = 68 (computed address)
    lw    x8, 0(x7)
    li    x4, 200
    bne   x8, x4, fail3

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
