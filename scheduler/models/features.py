"""
features.py -- Phase 13: the ONE feature-extraction function shared by
scheduler/training/train_scheduler.py (fitting) and, starting Phase
14, the runtime decision pipeline (inference). Keeping this in a
single module means the features a live scheduling decision sees are
guaranteed identical in shape/order to the features the model was
trained on -- a train/serve skew bug class this project would rather
not discover in Phase 14.

Feature vector (6 values, in this fixed order):
    [size_n, element_count, multiply_count, is_vecadd, is_dot, is_matmul]

Where each comes from:
  - size_n, element_count: the workload's own shape. element_count is
    the actual amount of output data produced (N for vecadd/dot,
    N*N for matmul) -- see scheduler/benchmarks/collect_dataset.py.
  - multiply_count: 0 for vecadd (pure ADD, native RV32I), size_n for
    dot (one multiply-accumulate per element), size_n**3 for matmul
    (textbook N^3 scalar multiplies). This is the single feature that
    is causally closest to *why* the CPU falls behind: RV32I (this
    project's ISA subset) has no hardware multiplier, so every
    CPU-side multiply is really ~10 shift-and-add instructions
    (rtl/'s mul32 routine, see docs/scheduler.md) while the
    accelerator does one MAC per cycle. vecadd's multiply_count is
    always 0, which is exactly why it's the only operation with a
    CPU-favorable data point in this project's measured dataset
    (N=1: 37 CPU cycles vs 39 accelerator cycles).
  - is_vecadd/is_dot/is_matmul: one-hot of the operation. Redundant
    with multiply_count in this project's own dataset (each operation
    maps to a distinct multiply_count formula), but a real scheduler
    receives the operation name directly as metadata rather than
    having to infer it, so it's kept as an explicit feature too.
"""

FEATURE_NAMES = [
    "size_n", "element_count", "multiply_count",
    "is_vecadd", "is_dot", "is_matmul",
]

# engine label encoding shared by training and inference
ENGINE_TO_LABEL = {"cpu": 0, "accelerator": 1}
LABEL_TO_ENGINE = {0: "cpu", 1: "accelerator"}


def multiply_count(operation: str, size_n: int) -> int:
    if operation == "vecadd":
        return 0
    if operation == "dot":
        return size_n
    if operation == "matmul":
        return size_n ** 3
    raise ValueError(f"unknown operation {operation!r}")


def element_count(operation: str, size_n: int) -> int:
    return size_n * size_n if operation == "matmul" else size_n


def extract_features(operation: str, size_n: int):
    """Return the 6-value feature vector (list[int]) for one workload,
    in FEATURE_NAMES order. `operation` must be one of "vecadd",
    "dot", "matmul" -- the only three kernels this project has
    measured data for (see docs/scheduler.md's scope/limitations
    section before extending this to a new kernel)."""
    ec = element_count(operation, size_n)
    mc = multiply_count(operation, size_n)
    return [
        size_n,
        ec,
        mc,
        1 if operation == "vecadd" else 0,
        1 if operation == "dot" else 0,
        1 if operation == "matmul" else 0,
    ]
