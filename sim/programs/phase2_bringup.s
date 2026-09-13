# phase2_bringup.s
#
# Phase 2 CPU bring-up program. Exercises R-type ALU ops, I-type ALU ops
# (including shifts), LUI/AUIPC, LW/SW, a taken branch, and a
# call/return pair (JAL/JALR), then parks in an infinite loop so the
# testbench can detect completion by PC no longer advancing.
#
# This is a hand-written smoke test for Phase 2, not the exhaustive
# per-instruction suite -- that is Phase 3's job (sim/programs will grow
# one directed test per instruction there). Expected final architectural
# state is asserted in sim/testbenches/tb_riscv_cpu.sv.

    li    x1, 10          # x1 = 10
    li    x2, 20          # x2 = 20
    add   x3, x1, x2      # x3 = 30
    sub   x4, x3, x1      # x4 = 20
    and   x5, x3, x4      # x5 = 30 & 20 = 20
    or    x6, x1, x2      # x6 = 10 | 20 = 30
    xor   x7, x1, x2      # x7 = 10 ^ 20 = 30
    slt   x8, x1, x2      # x8 = (10 < 20) = 1
    addi  x9, x0, -1      # x9 = 0xFFFFFFFF
    slli  x11, x1, 2      # x11 = 10 << 2 = 40
    srli  x12, x11, 1     # x12 = 40 >> 1 = 20
    lui   x16, 0x12345    # x16 = 0x12345000
    auipc x17, 0          # x17 = PC of this instruction

    sw    x3, 0(x0)       # mem[0] = 30
    lw    x13, 0(x0)      # x13 = 30

    addi  x0, x3, 999     # attempt to write x0 -- must be discarded
    add   x18, x0, x0     # x18 = 0 if x0 truly reads back as zero

    beq   x3, x13, eq_ok  # taken: x3 == x13
    addi  x10, x0, -999   # poison: must NOT execute
eq_ok:
    jal   x14, subroutine
    j     done
subroutine:
    addi  x15, x0, 42     # x15 = 42
    jalr  x0, x14, 0      # return
done:
    add   x10, x3, x1     # x10 = 30 + 10 = 40 (final result)
halt:
    j     halt            # spin forever; testbench detects PC steady-state
