"""
codegen.py -- compatibility shim. The co-scheduler's streams, layout,
reference values and RISC-V code generation moved to scheduler/framework/
(workloads.py, operations.py, rv32_codegen.py, verification.py, plans.py)
in the Phase 2 restructuring (docs/framework/). Same names, same behaviour.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from framework.operations import out_words, reference  # noqa: E402,F401
from framework.plans import serial_plan, validate  # noqa: E402,F401
from framework.rv32_codegen import (IMEM_WORDS, MMIO_BASE, OUT_START, accel_split,  # noqa: E402,F401
                                    cpu_body, layout, program)
from framework.verification import expected_words, write_expect_file  # noqa: E402,F401
from framework.workloads import FULL_STREAM, STREAMS  # noqa: E402,F401
