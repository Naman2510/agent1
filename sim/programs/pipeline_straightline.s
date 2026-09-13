# pipeline_straightline.s -- Phase 5 pipeline verification program.
#
# Deliberately contains NO branches and NO jumps. Phase 5's pipeline
# correctly computes branch/JAL/JALR targets and redirects the PC in EX
# (rtl/cpu/riscv_cpu_pipeline.sv), but does not yet flush the 2
# instructions already fetched from the sequential (wrong) path before
# that redirect takes effect -- that is Phase 6's job. Even an
# unconditional `j halt` parking loop would exercise that exact
# unhandled case, so this program has no halt loop either: the
# testbench (sim/testbenches/tb_pipeline.sv) runs for a precisely
# bounded number of cycles -- enough for every instruction below to
# reach WB -- and checks register state there, before the program would
# "run off the end" into zero-filled (and therefore illegal-opcode)
# memory. See docs/pipeline.md for the full explanation.
#
# Every RAW-dependent instruction pair below is separated by at least 3
# independent instructions (real work or explicit `nop`). That number
# was verified empirically, not assumed: this regfile's write (WB stage)
# and the consuming instruction's capture into id_ex_reg both happen via
# nonblocking assignment on the SAME clock edge when the gap is exactly
# 2 instructions, which is a same-edge race that resolves to the OLD
# (pre-write) value, not the new one -- a first attempt at this test
# using a 2-instruction gap failed for exactly that reason (see
# CHANGELOG.md Phase 5 entry). A gap of 3 independent instructions
# means the producer's WB has fully committed, and settled through
# ordinary combinational propagation, a full clock period before the
# consumer's ID-stage read is captured -- no same-edge ambiguity. This
# is exactly the property Phase 5 is verifying; closer dependencies are
# exactly what Phase 6's forwarding unit exists to fix, and are
# deliberately not used here.

    li   x1, 12
    li   x2, 10
    nop
    nop
    nop
    add  x3, x1, x2        # 12+10 = 22

    li   x4, 5
    li   x5, 3
    nop
    nop
    nop
    sub  x6, x4, x5        # 5-3 = 2

    andi x7, x1, 0xF       # x1 set long ago: 12 & 0xF = 12
    ori  x8, x2, 0x1       # x2 set long ago: 10 | 1 = 11
    xori x9, x1, 0xFF      # x1 set long ago: 12 ^ 0xFF = 0xF3

    nop
    nop
    nop
    slli x10, x2, 2        # x2 set long ago: 10 << 2 = 40

    nop
    nop
    nop
    srli x11, x10, 1       # x10 set 4 instrs ago: 40 >> 1 = 20

    li   x12, -16
    nop
    nop
    nop
    srai x13, x12, 2       # x12 set 4 instrs ago: -16 >> 2 = -4 (arithmetic)

    lui  x14, 0x12345      # no dependency: 0x12345000
    auipc x15, 0           # no dependency: x15 = its own address

    li   x16, 100
    nop
    nop
    nop
    sw   x16, 0(x0)        # x16 set 4 instrs ago: mem[0] = 100

    nop
    nop
    nop
    lw   x17, 0(x0)        # address needs only x0 (always ready); the
                            # VALUE depends on the sw above having
                            # committed its memory write well before
                            # this lw's own MEM stage -- true here by a
                            # wide margin (this is not a same-edge race
                            # like the regfile case above; the two MEM
                            # stages are far enough apart in absolute
                            # cycles that ordinary combinational
                            # propagation settles between them). -> x17=100

    nop
    nop
    nop
    add  x18, x17, x0      # x17 set 4 instrs ago: copy -> 100

    add  x19, x0, x0       # x0 hard-wire sanity check: must be 0
