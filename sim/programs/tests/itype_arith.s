# itype_arith.s -- Phase 3 directed test
# Covers: ADDI, SLTI, SLTIU, XORI, ORI, ANDI, plus negative immediates and
# the SLTIU rule that the immediate is sign-extended *then* treated as
# unsigned (RISC-V spec) -- tested explicitly with a negative immediate.

    li    x1, 5

    addi  x2, x1, -3       # 5 + (-3) = 2   (negative immediate)
    li    x4, 2
    bne   x2, x4, fail1

    addi  x3, x0, -1       # x3 = -1 = 0xFFFFFFFF
    li    x4, -1
    bne   x3, x4, fail2

    slti  x5, x3, 0        # signed:   -1 < 0            -> 1
    li    x4, 1
    bne   x5, x4, fail3

    sltiu x6, x3, 0        # unsigned: 0xFFFFFFFF < 0    -> 0
    li    x4, 0
    bne   x6, x4, fail4

    sltiu x7, x1, -1       # imm sign-extends to 0xFFFFFFFF (unsigned huge);
                           # 5 < 0xFFFFFFFF -> 1
    li    x4, 1
    bne   x7, x4, fail5

    xori  x8, x1, 0xF      # 5 ^ 0xF = 0xA
    li    x4, 0xA
    bne   x8, x4, fail6

    ori   x9, x1, 0x8      # 5 | 8 = 13
    li    x4, 13
    bne   x9, x4, fail7

    andi  x10, x1, 0x1     # 5 & 1 = 1
    li    x4, 1
    bne   x10, x4, fail8

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
