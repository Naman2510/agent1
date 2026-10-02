# mul_test.s -- end-to-end check of the optional RV32M MUL instruction on
# the pipelined CPU (rtl/cpu/riscv_cpu_pipeline.sv, ENABLE_MUL=1), run by
# sim/testbenches/tb_mul.sv. The same image also runs on an ENABLE_MUL=0
# core, where every `mul` must raise `illegal` and write nothing -- so
# each mul destination is pre-loaded with a 0x5A5A sentinel (or left at
# its reset value of 0) to make an unwanted write visible.
#
# Covers: basic / negative / negative*negative products, low-32-bit
# wraparound, back-to-back dependent muls (EX->EX forwarding), one
# instruction between producer and consumer (MEM->EX forwarding), a
# load feeding a mul (load-use stall), rd = x0 (read back through the
# normal read/forwarding path), and a branch comparing a
# mul result (forwarding into the branch unit). Expected values are in
# tb_mul.sv, computed in Python: (a * b) & 0xFFFFFFFF.

    li   x1, 6
    li   x2, 7
    li   x10, 0x5A5A
    mul  x10, x1, x2          # 42

    li   x3, -3
    li   x4, 5
    li   x11, 0x5A5A
    mul  x11, x3, x4          # -15 = 0xFFFFFFF1

    li   x5, -4
    li   x6, -6
    li   x12, 0x5A5A
    mul  x12, x5, x6          # 24

    li   x7, 0x12345678
    li   x8, 0x9ABCDEF0
    li   x13, 0x5A5A
    mul  x13, x7, x8          # low 32 bits: 0x242D2080

    li   x14, 0x5A5A
    mul  x14, x1, x2          # 42
    mul  x15, x14, x14        # 1764 -- x14 forwarded EX->EX

    mul  x16, x2, x2          # 49
    addi x0, x0, 0
    mul  x17, x16, x1         # 294 -- x16 forwarded MEM->EX

    li   x18, 0x1000
    li   x19, 11
    sw   x19, 0(x18)
    lw   x20, 0(x18)
    mul  x21, x20, x20        # 121 -- load-use stall before this mul

    mul  x0, x1, x2           # must leave x0 = 0
    add  x25, x0, x1          # 6: reads x0 back; 48 would mean the mul's 42
                              # was wrongly forwarded into an x0 read

    mul  x22, x1, x1          # 36
    li   x23, 36
    li   x24, 0x5A5A
    bne  x22, x23, skip       # mul result forwarded into the branch compare
    li   x24, 1               # reached only if x22 == 36
skip:
    li   x29, 0x20000000
    li   x30, 0xDEADBEEF
    sw   x30, 0(x29)
done:
    j    done
