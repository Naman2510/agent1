"""
planner.py -- compatibility shim. The cost model and plan search moved to
scheduler/framework/ (costmodel.py, planner.py, plans.py) in the Phase 2
restructuring (docs/framework/). Same names, same behaviour.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from framework.costmodel import RELOAD, plan_cost  # noqa: E402,F401
from framework.planner import exhaustive, local_search, oracle_plan, plan_stream  # noqa: E402,F401
from framework.plans import valid  # noqa: E402,F401
