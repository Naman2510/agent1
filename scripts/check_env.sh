#!/usr/bin/env bash
# Environment check for the AI-Directed RISC-V Heterogeneous Computing System.
#
# This project is developed entirely in software simulation on a normal
# laptop -- no FPGA board or other physical hardware is required. This
# script verifies that the tools each phase depends on are present and
# reports their versions, so problems are caught before a phase starts
# rather than mid-build.
#
# Exit code: 0 if all REQUIRED tools for the current phases are present,
# 1 otherwise. Tools only needed by later phases are reported but do not
# fail the check until that phase is reached (see the "later phase" notes).

set -u
FAIL=0

check() {
  # $5 (optional) overrides the flag used to print a version string,
  # since not every tool here accepts --version (iverilog uses -V,
  # gtkwave tries to open a GUI and needs a display, so we don't probe it).
  local name="$1" cmd="$2" required="$3" note="$4" vflag="${5:---version}"
  if command -v "$cmd" >/dev/null 2>&1; then
    local ver
    if [ "$vflag" = "none" ]; then
      ver="(installed; version probe skipped, see note)"
    else
      ver=$("$cmd" "$vflag" 2>&1 | head -n1)
    fi
    printf "  [OK]   %-28s %s\n" "$name" "$ver"
  else
    if [ "$required" = "yes" ]; then
      printf "  [FAIL] %-28s not found (%s)\n" "$name" "$note"
      FAIL=1
    else
      printf "  [--]   %-28s not found (%s)\n" "$name" "$note"
    fi
  fi
}

echo "== AI-RISCV environment check =="
echo
echo "-- Simulation (Phase 2+) --"
check "Icarus Verilog (iverilog)" iverilog yes "apt install iverilog" -V
check "Verilator"                 verilator yes "apt install verilator"
check "GTKWave"                   gtkwave  no  "apt install gtkwave; optional waveform viewer, needs a display" none
echo
echo "-- RISC-V cross toolchain (Phase 4+) --"
check "riscv64-unknown-elf-gcc"    riscv64-unknown-elf-gcc yes "apt install gcc-riscv64-unknown-elf"
check "riscv64-unknown-elf-objdump" riscv64-unknown-elf-objdump yes "apt install binutils-riscv64-unknown-elf"
check "riscv64-unknown-elf-objcopy" riscv64-unknown-elf-objcopy yes "apt install binutils-riscv64-unknown-elf"
echo
echo "-- Synthesis (Phase 12+) --"
check "Yosys" yosys no "apt install yosys; only required starting Phase 12"
echo
echo "-- Python / AI scheduler (Phase 13+) --"
check "python3" python3 yes "install Python 3.9+"
if command -v python3 >/dev/null 2>&1; then
  for pkg in numpy pandas sklearn; do
    if python3 -c "import $pkg" >/dev/null 2>&1; then
      printf "  [OK]   python module %-18s present\n" "$pkg"
    else
      printf "  [--]   python module %-18s not installed yet (pip install; only required starting Phase 13)\n" "$pkg"
    fi
  done
fi
echo
echo "-- Build tools --"
check "make" make yes "apt install make"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "Result: all tools required by the current phase are present."
else
  echo "Result: one or more REQUIRED tools are missing. Install them before continuing."
fi
exit "$FAIL"
