"""
simulator.py -- everything that touches the RTL simulators, moved
unchanged from scheduler/coschedule/run.py: the RTL file list, the
assembler call, Icarus Verilog and Verilator builds, and the runners that
parse each testbench's output.

Runners never guess. A run that does not print the line its parser
expects ends the process with the full simulator output (sys.exit),
which is how the original pipeline behaved.
"""

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RTL_FILES = [
    "rtl/cpu/riscv_pkg.sv", "rtl/alu/alu.sv", "rtl/regfile/regfile.sv",
    "rtl/decoder/decoder.sv", "rtl/decoder/imm_gen.sv", "rtl/cpu/control_unit.sv",
    "rtl/cpu/branch_unit.sv", "rtl/memory/imem.sv", "rtl/memory/dmem.sv",
    "rtl/pipeline/if_id_reg.sv", "rtl/pipeline/id_ex_reg.sv", "rtl/pipeline/ex_mem_reg.sv",
    "rtl/pipeline/mem_wb_reg.sv", "rtl/pipeline/forwarding_unit.sv",
    "rtl/pipeline/hazard_unit.sv", "rtl/cpu/perf_counters.sv",
    "rtl/cpu/riscv_cpu_pipeline.sv", "rtl/bus/soc_bus.sv", "rtl/bus/uart.sv",
    "rtl/bus/gpio.sv", "rtl/accelerator/accelerator.sv", "rtl/cpu/riscv_soc.sv",
]

VERILATOR_FLAGS = ["--binary", "--timing", "-Wall", "-Wno-DECLFILENAME", "-Wno-UNUSEDSIGNAL",
                   "-Wno-UNUSEDPARAM", "-Wno-PINMISSING", "-Wno-PINCONNECTEMPTY"]


def sh(cmd, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def icarus(tb_file, top, params):
    """Compile `tb_file` + the SoC RTL with Icarus; returns the .vvp path."""
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".vvp").name
    sh(["iverilog", "-g2012", "-o", out] + [f"-P{top}.{k}={v}" for k, v in params.items()]
       + RTL_FILES + [tb_file])
    return out


def assemble(src_text, stem, directory, imem_words):
    """Write `<directory>/<stem>.s`, assemble to `.hex`; returns the hex path."""
    os.makedirs(directory, exist_ok=True)
    s = os.path.join(directory, stem + ".s")
    with open(s, "w") as f:
        f.write(src_text)
    sh([sys.executable, "scripts/asm_to_hex.py", s, "-o", s[:-2] + ".hex",
        "--words", str(imem_words)])
    return s[:-2] + ".hex"


# --------------------------------------------------------------------------- tb_accel_phase_probe

PROBE_RE = re.compile(r"PROBE total=(\d+) intervals=(\d+)")
BUSY_RE = re.compile(r"BUSY rise=(\d+) fall=(-?\d+)")


def probe(vvp, hexfile):
    """(total cycles, [(busy_rise, busy_fall), ...]) of one program."""
    out = sh(["vvp", vvp, f"+HEXFILE={hexfile}"])
    m = PROBE_RE.search(out)
    if not m:
        sys.exit(f"probe failed for {hexfile}:\n{out}")
    return int(m.group(1)), [(int(a), int(b)) for a, b in BUSY_RE.findall(out)]


# --------------------------------------------------------------------------- tb_benchmark_soc

RESULT_RE = re.compile(r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+)")
CONFIG_RE = re.compile(r"BENCHMARK_CONFIG: name=\S+ ENABLE_MUL=(\d)")


def measure(vvp, hexfile, mul):
    """Cycle count of one program; asserts the simulated core's ENABLE_MUL."""
    out = sh(["vvp", vvp, f"+HEXFILE={hexfile}", "+NAME=x"])
    cfg, m = CONFIG_RE.search(out), RESULT_RE.search(out)
    if not cfg or int(cfg.group(1)) != mul or not m:
        sys.exit(f"measurement failed for {hexfile}:\n{out}")
    return int(m.group(2))


# --------------------------------------------------------------------------- tb_coschedule_check

def check_icarus(vvp, hexfile, expfile, nexp):
    out = sh(["vvp", vvp, f"+HEXFILE={hexfile}", f"+EXPECT={expfile}", f"+NCHECK={nexp}"])
    return "RESULT: ALL CHECKS PASSED" in out and f"CHECKED {nexp} output words" in out


def build_verilator(mul):
    d = tempfile.mkdtemp()
    # sized literal: ENABLE_MUL is a 1-bit `bit` parameter, and Verilator's
    # -Wall rejects a plain (32-bit) integer override as WIDTHTRUNC
    sh(["verilator"] + VERILATOR_FLAGS + [f"-GENABLE_MUL=1'b{mul}", "--top-module",
                                          "tb_coschedule_check"] + RTL_FILES
       + ["sim/testbenches/tb_coschedule_check.sv", "-o", "simv", "--Mdir", d])
    return d


def check_verilator(d, hexfile, expfile, nexp):
    r = subprocess.run([os.path.join(d, "simv"), f"+HEXFILE={hexfile}", f"+EXPECT={expfile}",
                        f"+NCHECK={nexp}"], cwd=ROOT, capture_output=True, text=True)
    return "RESULT: ALL CHECKS PASSED" in r.stdout and f"CHECKED {nexp} output words" in r.stdout
