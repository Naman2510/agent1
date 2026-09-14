# array_sum.s -- Phase 7 benchmark program.
#
# Sums 5 values stored in data memory using LW in a tight loop where the
# loaded value is used by the VERY NEXT instruction -- a real load-use
# hazard every iteration, unlike sum_loop.s (which has zero stalls).
# Together the two benchmarks give scripts/run_benchmarks.py's report a
# genuine contrast: a pure-ALU loop vs. a load-heavy one, exactly the
# kind of characteristic difference the AI scheduler (Phase 13+) will
# eventually need real measured data about.
#
# Values: 10, 20, 30, 40, 50 -> expected sum = 150.

    li   x1, 0            # base address, explicit (not relying on reset)
    li   x6, 10
    sw   x6, 0(x1)
    li   x6, 20
    sw   x6, 4(x1)
    li   x6, 30
    sw   x6, 8(x1)
    li   x6, 40
    sw   x6, 12(x1)
    li   x6, 50
    sw   x6, 16(x1)

    li   x2, 0            # sum
    li   x4, 0            # byte offset / address (base is x0, so this is
                           # also the absolute address)
    li   x7, 20           # end offset (5 words * 4 bytes)
loop:
    lw   x8, 0(x4)        # load-use hazard: x8 used by the very next
    add  x2, x2, x8       # instruction -> hazard_unit must stall 1 cycle
    addi x4, x4, 4
    blt  x4, x7, loop
done:
    j    done
