# data_hazard_forward.s -- Phase 6 directed test.
# Covers: EX/MEM forwarding (consumer immediately follows producer,
# 0-instruction gap) and MEM/WB forwarding (1-instruction gap). Both
# must produce the correct result with NO stall -- forwarding_unit.sv
# should resolve them on the fly.

    li   x1, 10
    li   x2, 20
    add  x3, x1, x2        # producer: x3 = 30
    add  x4, x3, x0        # consumer, 0 gap -> needs EX/MEM forward
    li   x5, 30
    bne  x4, x5, fail1

    add  x6, x1, x2        # producer: x6 = 30
    addi x9, x0, 999       # unrelated instruction (1-instruction gap)
    add  x7, x6, x0        # consumer, 1 gap -> needs MEM/WB forward
    li   x5, 30
    bne  x7, x5, fail2

    # A branch whose OWN operand needs forwarding (branch_unit must see
    # the forwarded value too, not raw id_ex data -- see
    # riscv_cpu_pipeline.sv's EX-stage comment on this).
    sub  x8, x1, x1         # x8 = 0
    beq  x8, x0, fwd_branch_ok   # 0 gap forward into the branch itself
    j    fail3
fwd_branch_ok:

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
