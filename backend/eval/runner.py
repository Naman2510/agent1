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
from eval.suites import retrieval as retrieval_suite

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
    parser.add_argument("--suite", required=True, choices=["lid", "retrieval"])
    parser.add_argument("--dataset", default="v1")
    parser.add_argument(
        "--failures", action="store_true", help="print every failing case with its reasoning"
    )
    args = parser.parse_args()

    if args.suite == "lid":
        return run_lid(args.dataset, show_failures=args.failures)
    if args.suite == "retrieval":
        import asyncio

        return asyncio.run(run_retrieval(args.dataset, show_failures=args.failures))
    return 2  # pragma: no cover - argparse restricts the choices


async def run_retrieval(dataset: str, *, show_failures: bool) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.config import get_settings
    from app.db.session import create_engine
    from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider

    path = DATASETS / dataset / "retrieval" / "cases.jsonl"
    if not path.exists():
        print(f"no retrieval cases at {path}", file=sys.stderr)
        return 2

    cases = retrieval_suite.load_cases(path)
    engine = create_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    print("=" * 70)
    print("suite            retrieval")
    print(f"dataset          {dataset} ({len(cases)} cases)")
    print(f"git sha          {git_sha()}")
    print(f"started          {datetime.now(UTC).isoformat(timespec='seconds')}")
    print(
        "corpus           datasets/v1/corpus (self-authored, 5 docs — see docs/adr/"
        "0006-embedding-model.md for the embedder substitution)"
    )
    print("=" * 70)

    async with factory() as session:
        embeddings = TfidfSvdEmbeddingProvider()
        await retrieval_suite.fit_embedder_on_corpus(session, embeddings)
        print(f"embedder         {embeddings.info.model}\n")

        configs = [
            ("vector_only", True, False),
            ("lexical_only", False, True),
            ("hybrid_rrf", True, True),
        ]
        results = {}
        for name, use_vector, use_lexical in configs:
            report = await retrieval_suite.run_config(
                session,
                cases,
                embeddings=embeddings,
                use_vector=use_vector,
                use_lexical=use_lexical,
            )
            results[name] = report
            print(f"--- {name} ---")
            print(report.render())
            print()

        bm25_report = await retrieval_suite.run_bm25_offline(session, cases)
        results["lexical_bm25_offline"] = bm25_report
        print("--- lexical_bm25_offline (reference only — not a shipped configuration) ---")
        print(bm25_report.render())
        print()

        # Per-language breakdown on the winning configuration, because a single aggregate would
        # hide exactly the gap this project exists to measure (ADR-0006's amendment).
        by_language: dict[str, list] = {}
        for case in cases:
            by_language.setdefault(case.language, []).append(case)
        print("--- hybrid_rrf, per language ---")
        print(
            f"{'language':10s} {'n':>3s} {'recall@5':>9s} "
            f"{'recall@10':>10s} {'mrr':>7s} {'ndcg@10':>8s}"
        )
        for language, lang_cases in sorted(by_language.items()):
            lang_report = await retrieval_suite.run_config(
                session, lang_cases, embeddings=embeddings, use_vector=True, use_lexical=True
            )
            s = lang_report.summary()
            print(
                f"{language:10s} {len(lang_cases):3d} {s['recall@5']:9.3f} "
                f"{s['recall@10']:10.3f} {s['mrr']:7.3f} {s['ndcg@10']:8.3f}"
            )

        if show_failures:
            print("\nhybrid_rrf failures (recall@10 == 0)")
            for metric in results["hybrid_rrf"].per_query:
                if metric.recall_at_k.get(10, 0.0) == 0.0:
                    print(
                        f"  {metric.query_id}: 0 of {len(metric.relevant)} "
                        "relevant chunks found in top 10"
                    )

    await engine.dispose()

    print()
    print(
        "summary_metrics "
        + json.dumps({name: r.summary() for name, r in results.items()}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
