# AI-Directed RISC-V Heterogeneous Computing System
#
# This Makefile grows one target per phase, added when that phase lands
# (see CHANGELOG.md / README.md for phase status). Targets for phases
# that don't exist yet are intentionally absent rather than stubbed out
# with no-ops, so `make <target>` failing with "No rule to make target"
# honestly reflects that the phase isn't built yet.

.PHONY: check-env help sim_cpu test_isa run_c_demo sim_pipeline test_hazards waves test_perf benchmarks sim_soc test_accel test_accel_custom test_bench_correctness benchmarks_accel synthesize test_scheduler_correctness collect_scheduler_dataset train_scheduler test_scheduler_heldout_correctness collect_scheduler_heldout_dataset evaluate_scheduler_accuracy test_dynamic_scheduler_correctness run_dynamic_scheduler_demo test_mixed_workload_correctness run_mixed_workload_demo

help:
	@echo "Available targets:"
	@echo "  check-env    - verify required toolchain is installed (scripts/check_env.sh)"
	@echo "  sim_cpu      - assemble and run the Phase 2 single-cycle CPU testbench"
	@echo "                 under both Icarus Verilog and Verilator"
	@echo "  test_isa     - run the Phase 3 directed instruction test suite"
	@echo "                 (sim/programs/tests/) under both simulators"
	@echo "  run_c_demo   - Phase 4: compile software/baremetal/add_test.c with the"
	@echo "                 real RISC-V GCC toolchain and run it on the CPU"
	@echo "  sim_pipeline - Phase 5: assemble and run the pipelined CPU testbench"
	@echo "                 under both Icarus Verilog and Verilator"
	@echo "  test_hazards - Phase 6: run the pipeline hazard directed test suite"
	@echo "                 (sim/programs/pipeline_tests/) under both simulators"
	@echo "  waves        - Phase 6: generate GTKWave .vcd waveforms for the"
	@echo "                 hazard directed tests (sim/waveforms/)"
	@echo "  test_perf    - Phase 7: verify benchmark correctness + performance"
	@echo "                 counters (sim/programs/benchmarks/) under both simulators"
	@echo "  benchmarks   - Phase 7: run the benchmarks and write"
	@echo "                 results/performance_report.md from real measured data"
	@echo "  sim_soc      - Phase 8: assemble and run the top-level SoC testbench"
	@echo "                 (RAM/UART/GPIO through the real address-decoded bus)"
	@echo "                 under both Icarus Verilog and Verilator"
	@echo "  test_accel   - Phase 9: run the accelerator unit test (direct MMIO)"
	@echo "                 and the CPU-driven end-to-end demo (vector add,"
	@echo "                 dot product, matrix multiply) under both simulators"
	@echo "  test_accel_custom - Phase 10: run the ACCEL.* custom-instruction"
	@echo "                 end-to-end demo under both simulators"
	@echo "  test_bench_correctness - Phase 11: verify the CPU-only benchmark"
	@echo "                 kernels against Python-computed expected results"
	@echo "  benchmarks_accel - Phase 11: run CPU-only vs. accelerator-driven"
	@echo "                 benchmarks and write results/accelerator_benchmark_report.md"
	@echo "  synthesize   - Phase 12: run every module through Yosys (iCE40) and"
	@echo "                 write results/synthesis_report.md (requires yosys)"
	@echo "  test_scheduler_correctness - Phase 13: verify the 12 new-size scheduler"
	@echo "                 benchmark programs against Python-computed expected results"
	@echo "  collect_scheduler_dataset - Phase 13: run all 11 workloads (CPU + accelerator)"
	@echo "                 and write scheduler/training/dataset.csv from real measured cycles"
	@echo "  train_scheduler - Phase 13: fit the AI scheduler decision-tree model on"
	@echo "                 dataset.csv and write results/scheduler_report.md"
	@echo "                 (needs numpy/pandas/scikit-learn: see .venv/ in docs/scheduler.md)"
	@echo "  test_scheduler_heldout_correctness - Phase 14: verify the 9 held-out"
	@echo "                 scheduler workloads against Python-computed expected results"
	@echo "  collect_scheduler_heldout_dataset - Phase 14: write"
	@echo "                 scheduler/training/heldout_dataset.csv from real measured cycles"
	@echo "  evaluate_scheduler_accuracy - Phase 14: score the trained model's decisions"
	@echo "                 against held-out ground truth + write results/scheduler_accuracy_report.md"
	@echo "  test_dynamic_scheduler_correctness - Phase 15: verify the dynamic-scheduling"
	@echo "                 demo (+ 3 static baselines) against Python-computed expected results"
	@echo "  run_dynamic_scheduler_demo - Phase 15: measure the dynamic scheduler's real"
	@echo "                 runtime overhead + write results/dynamic_scheduling_report.md"
	@echo "  test_mixed_workload_correctness - Phase 16: verify the 12-workload mixed"
	@echo "                 heterogeneous stream demo (+ 3 static baselines)"
	@echo "  run_mixed_workload_demo - Phase 16: measure the dynamic scheduler at larger"
	@echo "                 scale + write results/mixed_workloads_report.md"
	@echo ""
	@echo "Phase targets are added here as each phase is implemented;"
	@echo "see README.md for current phase status."

check-env:
	@./scripts/check_env.sh

sim_cpu:
	@./scripts/run_sim_phase2.sh

test_isa:
	@python3 scripts/run_directed_tests.py

run_c_demo:
	@./scripts/run_c_program.sh add_test 30

sim_pipeline:
	@./scripts/run_sim_pipeline.sh

test_hazards:
	@python3 scripts/run_pipeline_hazard_tests.py

waves:
	@./scripts/generate_waveforms.sh

test_perf:
	@./scripts/run_perf_counters.sh

benchmarks:
	@python3 scripts/run_benchmarks.py

sim_soc:
	@./scripts/run_sim_soc.sh

test_accel:
	@./scripts/run_sim_accel.sh

test_accel_custom:
	@./scripts/run_sim_accel_custom.sh

test_bench_correctness:
	@./scripts/run_bench_correctness.sh

benchmarks_accel:
	@python3 scripts/run_benchmarks_accel.py

synthesize:
	@./scripts/run_synthesis.sh

test_scheduler_correctness:
	@./scripts/run_scheduler_correctness.sh

collect_scheduler_dataset:
	@python3 scheduler/benchmarks/collect_dataset.py

train_scheduler:
	@.venv/bin/python3 scheduler/training/train_scheduler.py

test_scheduler_heldout_correctness:
	@./scripts/run_scheduler_heldout_correctness.sh

collect_scheduler_heldout_dataset:
	@python3 scheduler/benchmarks/collect_heldout_dataset.py

evaluate_scheduler_accuracy:
	@.venv/bin/python3 scheduler/inference/evaluate_accuracy.py

test_dynamic_scheduler_correctness:
	@./scripts/run_dynamic_scheduler_correctness.sh

run_dynamic_scheduler_demo:
	@python3 scheduler/runtime/run_dynamic_scheduler_demo.py

test_mixed_workload_correctness:
	@./scripts/run_mixed_workload_correctness.sh

run_mixed_workload_demo:
	@python3 scheduler/runtime/run_mixed_workload_demo.py
