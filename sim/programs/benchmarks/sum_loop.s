# sum_loop.s -- Phase 7 benchmark program.
#
# Sums 1..N into x2 using a real branch-driven loop (not synthetic
# NOP-padded straight-line code like the earlier phases' plumbing
# tests) -- the point of this program is to exercise the pipeline the
# way a real, tight, hazard-heavy loop actually would: a loop-carried
# dependency on the accumulator, an immediately-following branch
# condition depending on the just-updated loop counter, and a taken
# branch every iteration but the last. This is intended for
# scripts/run_benchmarks.py to read performance counters after, not to
# self-check via x31 (see sim/testbenches/tb_perf_counters.sv, which
# checks the actual sum in x2 directly).
#
# N=10, so x2 should equal 55 (1+2+...+10) when the loop exits.

    li   x1, 10          # N
    li   x2, 0           # sum
    li   x4, 1           # i
    addi x11, x1, 1      # loop bound = N+1
loop:
    add  x2, x2, x4      # sum += i      (loop-carried; gap=3 -> regfile bypass)
    addi x4, x4, 1       # i++
    blt  x4, x11, loop   # continue while i < N+1 (i is gap=1 here -> EX/MEM forward)
done:
    j    done            # safe now that Phase 6 flushes taken jumps correctly
