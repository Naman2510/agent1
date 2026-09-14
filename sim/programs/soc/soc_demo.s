# soc_demo.s -- Phase 8 SoC-level directed test.
#
# Exercises RAM, GPIO, and UART through the REAL address-decoded SoC bus
# (rtl/bus/soc_bus.sv) instead of talking to any peripheral directly --
# this is what proves the memory map in docs/soc.md actually routes
# accesses to the right device, not just that each peripheral module
# works in isolation.
#
# GPIO_IN is driven externally by the testbench (sim/testbenches/
# tb_soc.sv) to a known constant BEFORE reset deasserts, so this
# program's read of it has a fixed expected value.

    # ---- RAM (0x00000000): write + read back through the bus ----
    li   x1, 0x00000000     # RAM base
    li   x2, 0x1234
    sw   x2, 0(x1)
    lw   x3, 0(x1)
    bne  x3, x2, fail1

    # ---- GPIO (0x20000000): write GPIO_OUT, read it back ----
    li   x4, 0x20000000     # GPIO base
    li   x5, 0xA5
    sw   x5, 0(x4)           # GPIO_OUT = 0xA5
    lw   x6, 0(x4)           # read GPIO_OUT back through the bus
    bne  x6, x5, fail2

    # ---- GPIO_IN (0x20000004): read the testbench-driven input ----
    lw   x7, 4(x4)
    li   x8, 0xCAFEBABE      # value tb_soc.sv drives on gpio_in
    bne  x7, x8, fail3

    # ---- UART (0x10000000): send two bytes via TXDATA, polling STATUS
    # between them exactly like real driver code would -- uart.sv's
    # busy flag is real (it drops a write that arrives while busy), so
    # a correct driver always polls first; this loop is that driver,
    # not a shortcut around it.
    li   x9,  0x10000000     # UART base
    li   x10, 72             # 'H'
    sw   x10, 0(x9)

wait_tx1:
    lw    x12, 4(x9)         # STATUS
    andi  x12, x12, 1
    bne   x12, x0, wait_tx1  # loop while busy

    li   x11, 73             # 'I'
    sw   x11, 0(x9)

wait_tx2:
    lw    x12, 4(x9)         # STATUS
    andi  x12, x12, 1
    bne   x12, x0, wait_tx2  # loop while busy

    # Both bytes drained: STATUS must now read not-busy.
    lw   x12, 4(x9)
    bne  x12, x0, fail4

    j test_pass
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
test_pass:
    li x31, 1
done:
    j done
