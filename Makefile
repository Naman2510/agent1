# AI-Directed RISC-V Heterogeneous Computing System
#
# This Makefile grows one target per phase, added when that phase lands
# (see CHANGELOG.md / README.md for phase status). Targets for phases
# that don't exist yet are intentionally absent rather than stubbed out
# with no-ops, so `make <target>` failing with "No rule to make target"
# honestly reflects that the phase isn't built yet.

.PHONY: check-env help sim_cpu

help:
	@echo "Available targets:"
	@echo "  check-env  - verify required toolchain is installed (scripts/check_env.sh)"
	@echo "  sim_cpu    - assemble and run the Phase 2 single-cycle CPU testbench"
	@echo "               under both Icarus Verilog and Verilator"
	@echo ""
	@echo "Phase targets are added here as each phase is implemented;"
	@echo "see README.md for current phase status."

check-env:
	@./scripts/check_env.sh

sim_cpu:
	@./scripts/run_sim_phase2.sh
