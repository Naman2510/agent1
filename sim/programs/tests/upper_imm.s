# upper_imm.s -- Phase 3 directed test
# Covers: LUI, AUIPC.
#
# The AUIPC checks are written as *relative* invariants (the difference
# between two AUIPC results at known instruction spacing) rather than
# comparing against a hand-computed absolute address, so this test stays
# correct even if instructions are added earlier in the file.

    lui   x1, 0x12345
    li    x4, 0x12345000
    bne   x1, x4, fail1

    auipc x2, 0            # x2 = address of THIS instruction
    auipc x3, 0            # x3 = x2's address + 4 (one instruction later)
    sub   x5, x3, x2
    li    x4, 4
    bne   x5, x4, fail2

    auipc x6, 1            # x6 = (address of THIS instruction) + 0x1000,
                           # and this instruction is exactly 5 words after
                           # the `auipc x2, 0` above (20 bytes: auipc x3,
                           # sub, li, bne come in between)
    sub   x7, x6, x2
    li    x4, 0x1014       # 0x1000 + 20
    bne   x7, x4, fail3

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
