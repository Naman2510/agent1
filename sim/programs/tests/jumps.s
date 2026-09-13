# jumps.s -- Phase 3 directed test
# Covers: JAL, JALR, and a return-address register dependency (JAL writes
# a return address into a register; JALR later uses that same register's
# value to redirect the PC). A poison instruction sits right after the
# JALR so a JALR that fails to redirect PC (falls through instead) is
# caught rather than coincidentally landing on the right place.

    jal   x1, target        # jump to target; x1 = return addr (unused here)
    j     fail1              # poison: must be skipped by the jump
target:
    li    x2, 42
    li    x4, 42
    bne   x2, x4, fail2

    jal   x3, func           # x3 = address of the next instruction
    j     after_call
func:
    li    x5, 7
    jalr  x0, x3, 0          # must redirect PC to "j after_call", above
    li    x31, 0x80000099    # poison: only reached if JALR fails to jump
    j     done
after_call:
    li    x4, 7
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
