"""
scheduler/framework -- the co-scheduler's components as separate modules
(docs/framework/EXTENSIBILITY_ROADMAP.md, Phase 2).

Layering (each module imports only from those above it):

  operations    the operation registry: per-op CPU body, accelerator body,
                output size, reference result. The ONLY place that imports
                the verified Phase 15 task bodies.
  workloads     the task-stream catalogue (phase15, phase16, full24).
  plans         plan format, validity, description.
  costmodel     profile records + the plan cost model.
  planner       plan search (local search, exhaustive optimum).
  rv32_codegen  RISC-V program generation for the existing SoC
                (memory layout, start/collect window splice).
  verification  expected output words; expect-file writer.
  simulator     RTL file list, assembler, Icarus/Verilator builds, testbench
                runners and output parsing.
  profiler      per-task profiling on the simulated SoC.

Phase 2 is a pure restructuring. Every function here is moved from
scheduler/coschedule/{codegen,planner,run}.py with its behaviour unchanged,
and tests/test_framework_equivalence.py checks that every generated program
is byte-identical to the committed baseline.
"""
