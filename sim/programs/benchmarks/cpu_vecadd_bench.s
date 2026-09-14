# cpu_vecadd_bench.s -- Phase 11 benchmark: CPU-only vector add, N=16,
# no hardware accelerator involved at all. A[i] = i+1, B[i] = i+2 for
# i in [0,16), computed by a real setup loop (not hand-unrolled
# constants -- see sim/programs/benchmarks/array_sum.s for why that
# doesn't scale past a handful of elements), then OUT[i] = A[i]+B[i]
# by a second real loop.
#
# Correctness for this exact code structure (at a small, hand-checkable
# N) is established by sim/testbenches/tb_bench_cpu_correctness.sv
# BEFORE this benchmark-scale (N=16) version is trusted -- same
# "verify once, trust as benchmark thereafter" pattern
# docs/pipeline.md's Phase 7 section already established. No x31
# pass/fail check here: adding one would inflate the measured
# instruction/cycle count with verification overhead that has nothing
# to do with the vector-add kernel itself.
#
# Completion signal: once OUT is fully written, this program writes a
# fixed sentinel (0xDEADBEEF) to GPIO_OUT and only then enters its
# halt loop -- sim/testbenches/tb_benchmark_soc.sv watches for exactly
# this and snapshots the performance counters the instant it appears,
# rather than requiring a hand-picked cycle count (see that
# testbench's header comment for why).

    li   x1, 0x1000        # &A[0]  (plain RAM; no accelerator involved)
    li   x2, 0x2000        # &B[0]
    li   x3, 0x3000        # &OUT[0]
    li   x9, 16              # N
    li   x29, 0x20000000     # GPIO base  (computed early, not in the
                               # timed tail -- see header comment)
    li   x30, 0xDEADBEEF      # sentinel value

    li   x4, 0                # i
setup_loop:
    addi x5, x4, 1              # A[i] = i+1
    slli x6, x4, 2                # byte offset = i*4
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2                # B[i] = i+2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, setup_loop

    li   x4, 0
compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, compute_loop

    sw   x30, 0(x29)            # GPIO_OUT = sentinel: work is done
done:
    j    done
