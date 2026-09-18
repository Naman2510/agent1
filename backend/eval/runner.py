"""Evaluation entrypoint.

Every run records what produced it — suite, dataset version, git SHA, config — because a metric
without those is not a result (EVALUATION.md §1). Writing the row to `evaluation_runs` needs the
database and lands with the eval API in Phase 8; until then the runner prints the same fields it
will persist, so the discipline is established before the plumbing.

    python -m eval.runner --suite lid --dataset v1
    python -m eval.runner --suite lid --dataset v1 --failures
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from eval.suites import lid

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS = REPO_ROOT / "datasets"


def git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # A run that cannot be tied to a commit is not reproducible, and saying so is better than
        # emitting a number that looks authoritative.
        return "unknown"


def run_lid(dataset: str, *, show_failures: bool) -> int:
    path = DATASETS / dataset / "lid" / "cases.jsonl"
    if not path.exists():
        print(f"no LID cases at {path}", file=sys.stderr)
        return 2

    cases = lid.load_cases(path)
    result = lid.run(cases)

    print("=" * 62)
    print("suite            lid")
    print(f"dataset          {dataset}")
    print(f"git sha          {git_sha()}")
    print(f"started          {datetime.now(UTC).isoformat(timespec='seconds')}")
    print("router           app.agent.lang.router (lexicon + script, no model)")
    print("=" * 62)
    print()
    print("SIGNAL — did the utterance itself identify its language?")
    print("(no usable signal counts as `unknown`, even where the router then answered correctly)")
    print()
    print(result.signal.render())
    print()
    print("ROUTED — what the router actually chose, sticky prior included")
    print("(closer to what a student experiences; a fresh session defaults to English)")
    print()
    print(result.routed.render())
    print()
    print(
        "BIAS: these cases were authored by the same person who wrote the lexicon under test.\n"
        "They measure internal consistency and guard against regressions. They are NOT evidence\n"
        "of accuracy on real student speech — see datasets/v1/MANIFEST.yaml."
    )

    failures = [o for o in result.outcomes if not o.passed]
    if show_failures and failures:
        print()
        print(f"failures ({len(failures)})")
        for outcome in failures:
            print(
                f"  {outcome.case.id:10s} expected {outcome.case.language:8s} "
                f"got {outcome.predicted:8s} | {outcome.case.text}"
            )
            print(f"             {outcome.explanation}")

    print()
    print(
        "summary_metrics "
        + json.dumps(
            {
                "signal": result.signal.summary(),
                "routed": result.routed.summary(),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a VaaniOS evaluation suite.")
    parser.add_argument("--suite", required=True, choices=["lid"])
    parser.add_argument("--dataset", default="v1")
    parser.add_argument(
        "--failures", action="store_true", help="print every failing case with its reasoning"
    )
    args = parser.parse_args()

    if args.suite == "lid":
        return run_lid(args.dataset, show_failures=args.failures)
    return 2  # pragma: no cover - argparse restricts the choices


if __name__ == "__main__":
    raise SystemExit(main())
