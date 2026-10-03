# Co-Scheduler Scorecard: 100/100

Computed by `scheduler/coschedule/run.py` from the measurements in `results/coschedule_report.md`, against the thresholds pre-registered in `docs/coschedule_scorecard.md` (commit `9808c32`, made before the co-scheduler existed). Not hand-entered.

| # | Metric | Result | Evidence |
|---|---|---|---|
| 1 | Correctness | PASS (10) | 18 programs, 2058 output words, all checked on Icarus + Verilator; failures: none |
| 2 | Never worse | PASS (10) | phase15/rv32i: +3.7%, phase15/mul: +4.8%, phase16/rv32i: +4.0%, phase16/mul: +4.0%, full24/rv32i: +7.7%, full24/mul: +8.7% |
| 3 | Real speedup (RV32I) >= 5% | PASS (10) | full24/rv32i: 7.75% (510 cycles) |
| 4 | Real speedup (MUL core) >= 5% | PASS (10) | full24/mul: 8.71% (573 cycles) |
| 5 | Beats the old ceiling >= 10x | PASS (10) | co-schedule gain 510 cycles vs. serial ceiling (always-accel - oracle) 10 cycles = 51.0x |
| 6 | Model fidelity <= 5% | PASS (10) | max |error| over co-schedules: 2.25% |
| 7 | Planner quality <= 1% of optimum | PASS (10) | rv32i: planner 371 vs. optimum 371 (+0.00%), mul: planner 364 vs. optimum 364 (+0.00%) |
| 8 | Zero hardware cost | PASS (10) | `git diff 9808c32 -- rtl/` is empty |
| 9 | Reproducible | PASS (10) | `make coschedule` regenerates profiles, plans, programs, checks and measurements; every program measured twice in this run: identical. The full `make demo` regression (which includes this target) is run and recorded in CHANGELOG.md's co-scheduler entry. |
| 10 | Honest reporting | PASS (10) | report lists every stream x core result, the model-error table and the method's limits |
