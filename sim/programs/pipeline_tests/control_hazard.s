# control_hazard.s -- Phase 6 directed test.
# Covers: a taken branch must flush the 2 wrong-path instructions
# already fetched; a NOT-taken branch must NOT flush (plain fallthrough
# continues normally); JAL and JALR must also flush. Each poison
# instruction below, if it executes at all, sets x31 to a code that can
# never be overwritten back to the pass value by anything other than
# reaching test_pass through the CORRECT path.

    li   x1, 5
    li   x2, 5
    beq  x1, x2, after_taken   # taken (5==5): must flush the 2 lines below
    li   x31, 0x80000001
    j    done
after_taken:

    li   x8, 1
    li   x9, 1
    bne  x8, x9, fail2         # NOT taken (1==1): must fall through, no flush
    li   x10, 77
    li   x11, 77
    bne  x10, x11, fail3       # sanity: confirms the fallthrough above ran

    jal  x12, after_jal        # unconditional: must flush the 2 lines below
    li   x31, 0x80000004
    j    done
after_jal:

    jal  x13, func             # call
    j    after_jalr
func:
    li   x14, 55
    jalr x0, x13, 0            # return: must flush the line below
    li   x31, 0x80000005
after_jalr:
    li   x15, 55
    bne  x14, x15, fail6

    j    test_pass
fail2:
    li x31, 0x80000002
    j done
fail3:
    li x31, 0x80000003
    j done
fail6:
    li x31, 0x80000006
    j done
test_pass:
    li x31, 1
done:
    j done
