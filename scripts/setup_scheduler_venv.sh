#!/usr/bin/env bash
# setup_scheduler_venv.sh -- Phase 13: create the Python virtual
# environment `make train_scheduler` runs against.
#
# Why a venv at all: this environment's system-wide numpy install is
# broken for the interpreter `python3` resolves to (`import numpy`
# fails with "No module named 'numpy.core._multiarray_umath'", an
# apt/pip packaging conflict, not anything this project did). A venv
# with numpy/pandas/scikit-learn installed fresh from PyPI sidesteps
# it cleanly rather than fighting the system install. If your machine
# doesn't have this problem, `pip install numpy pandas scikit-learn`
# into any Python 3 environment and pointing train_scheduler at it
# works just as well -- the venv here is a convenience, not a
# requirement of the code itself.
#
# Usage: scripts/setup_scheduler_venv.sh

set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet numpy pandas scikit-learn

echo "Created .venv/ with:"
.venv/bin/python3 -c "import numpy, pandas, sklearn; \
print(f'  numpy {numpy.__version__}'); \
print(f'  pandas {pandas.__version__}'); \
print(f'  scikit-learn {sklearn.__version__}')"
echo
echo "Run 'make train_scheduler' next."
