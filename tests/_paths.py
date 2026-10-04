"""Shared path setup: makes `framework` (scheduler/framework) importable."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scheduler"))
COSCHED_DIR = os.path.join(ROOT, "scheduler", "coschedule")
PROG_DIR = os.path.join(ROOT, "sim", "programs", "coschedule")
