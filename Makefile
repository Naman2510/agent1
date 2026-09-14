# AI-Directed RISC-V Heterogeneous Computing System
#
# This Makefile grows one target per phase, added when that phase lands
# (see CHANGELOG.md / README.md for phase status). Targets for phases
# that don't exist yet are intentionally absent rather than stubbed out
# with no-ops, so `make <target>` failing with "No rule to make target"
# honestly reflects that the phase isn't built yet.

.PHONY: check-env help sim_cpu test_isa run_c_demo sim_pipeline test_hazards waves test_perf benchmarks

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
