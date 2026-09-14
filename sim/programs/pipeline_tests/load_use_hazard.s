# load_use_hazard.s -- Phase 6 directed test.
# Covers: the load-use hazard (a load's result needed by the VERY NEXT
# instruction). Forwarding alone can't fix this -- EX/MEM would only
# have the load's address, not its data -- so hazard_unit.sv must stall
# the pipeline for one cycle; forwarding_unit.sv's MEM/WB path then
# supplies the value once the load reaches that stage.

    li   x1, 64            # address
    li   x2, 42
    sw   x2, 0(x1)
    lw   x3, 0(x1)          # load
    add  x4, x3, x0         # 0 gap after a LOAD -> must stall, then forward
    li   x5, 42
    bne  x4, x5, fail1

    # A load used by the ALSO-immediately-following instruction's second
    # operand (not just the first), and by a STORE's address register.
    li   x6, 68
    li   x7, 99
    sw   x7, 0(x6)
    lw   x8, 0(x6)           # load
    sw   x8, 4(x6)            # 0 gap, load used as STORE's data operand
    lw   x9, 4(x6)
    li   x5, 99
    bne  x9, x5, fail2

    # A load whose result feeds a branch immediately (load-use AND
    # control-hazard-adjacent in the same handful of instructions).
    li   x10, 72
    li   x11, 7
    sw   x11, 0(x10)
    lw   x12, 0(x10)          # load
    beq  x12, x11, load_use_branch_ok  # 0 gap into a branch condition
    j    fail3
load_use_branch_ok:

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
test_pass:
    li x31, 1
done:
    j done
