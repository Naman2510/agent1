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

from eval.suites import agent as agent_suite
from eval.suites import injection as injection_suite
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
    parser.add_argument(
        "--suite", required=True, choices=["lid", "retrieval", "injection", "agent"]
    )
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
    if args.suite == "injection":
        import asyncio

        return asyncio.run(run_injection(args.dataset))
    if args.suite == "agent":
        import asyncio

        return asyncio.run(run_agent(args.dataset))
    return 2  # pragma: no cover - argparse restricts the choices


async def run_injection(dataset: str) -> int:
    """Runs against a throwaway student/session row that is never committed (like run_retrieval,
    this suite mutates nothing on success — the whole point is that it does not — so there is
    nothing here worth persisting, and rolling back on close leaves no trace in a shared database).
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.agent.tools.base import ToolContext
    from app.agent.tools.registry import DEFAULT_REGISTRY
    from app.core.config import get_settings
    from app.db.models import Session, Student, User, UserRole
    from app.db.session import create_engine
    from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
    from app.providers.reranker.base import NoopReranker
    from app.rag.service import RagService

    path = DATASETS / dataset / "agent" / "injection_cases.jsonl"
    if not path.exists():
        print(f"no injection cases at {path}", file=sys.stderr)
        return 2

    cases = injection_suite.load_cases(path)
    engine = create_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    print("=" * 70)
    print("suite            injection")
    print(f"dataset          {dataset} ({len(cases)} cases)")
    print(f"git sha          {git_sha()}")
    print(f"started          {datetime.now(UTC).isoformat(timespec='seconds')}")
    print(
        "measures         whether a model already persuaded by injected text is still blocked "
        "before mutating anything — NOT whether a real model resists the injection itself "
        "(no LLM call is made; see eval/suites/injection.py)"
    )
    print("=" * 70)

    async with factory() as session:
        user = User(
            email="eval-injection@example.invalid",
            password_hash="x",  # noqa: S106 - throwaway actor for a run that is never committed
            role=UserRole.STUDENT,
        )
        session.add(user)
        await session.flush()
        student = Student(user_id=user.id, display_name="eval-injection")
        session.add(student)
        await session.flush()
        conversation_session = Session(student_id=student.id, transport="text")
        session.add(conversation_session)
        await session.flush()

        rag = RagService(session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker())
        ctx = ToolContext(
            student_id=student.id,
            session_id=conversation_session.id,
            turn_index=0,
            db=session,
            rag=rag,
            citation_sources={},
        )
        report = await injection_suite.run(cases, registry=DEFAULT_REGISTRY, ctx=ctx)
        # Deliberately not committed — see the docstring above.

    await engine.dispose()

    print(report.render())
    print()
    print("summary_metrics " + json.dumps(report.summary(), sort_keys=True))
    return 0 if not report.executed else 1


async def run_agent(dataset: str) -> int:
    """Runs against throwaway rows that are never committed — see run_injection's docstring for
    why. See eval/suites/agent.py's own module docstring for what this suite does and does not
    measure: allowlist coverage and pipeline mechanics are real; a real model's tool-selection
    judgement is not, for lack of an Anthropic API key in this sandbox.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.agent.tools.base import ToolContext
    from app.agent.tools.registry import DEFAULT_REGISTRY
    from app.core.config import get_settings
    from app.db.models import Session, Student, User, UserRole
    from app.db.session import create_engine
    from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
    from app.providers.reranker.base import NoopReranker
    from app.rag.service import RagService

    path = DATASETS / dataset / "agent" / "scenarios.jsonl"
    if not path.exists():
        print(f"no agent scenarios at {path}", file=sys.stderr)
        return 2

    scenarios = agent_suite.load_cases(path)
    engine = create_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    print("=" * 70)
    print("suite            agent")
    print(f"dataset          {dataset} ({len(scenarios)} scenarios)")
    print(f"git sha          {git_sha()}")
    print(f"started          {datetime.now(UTC).isoformat(timespec='seconds')}")
    print(
        "measures         allowlist coverage and real pipeline execution under a scripted "
        "model — NOT a real model's tool-selection accuracy (no LLM call is made; see "
        "eval/suites/agent.py)"
    )
    print("=" * 70)

    report = agent_suite.AgentReport()
    for scenario in scenarios:
        report.allowlist_checks.append(agent_suite.check_allowlist_coverage(scenario))

    async with factory() as session:
        user = User(
            email="eval-agent@example.invalid",
            password_hash="x",  # noqa: S106 - throwaway actor for a run that is never committed
            role=UserRole.STUDENT,
        )
        session.add(user)
        await session.flush()
        student = Student(user_id=user.id, display_name="eval-agent")
        session.add(student)
        await session.flush()

        for scenario in scenarios:
            conversation_session = Session(student_id=student.id, transport="text")
            session.add(conversation_session)
            await session.flush()
            rag = RagService(
                session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker()
            )
            ctx = ToolContext(
                student_id=student.id,
                session_id=conversation_session.id,
                turn_index=0,
                db=session,
                rag=rag,
                citation_sources={},
            )
            if scenario.run_pipeline:
                report.pipeline_outcomes.append(
                    await agent_suite.run_pipeline_scenario(
                        scenario, registry=DEFAULT_REGISTRY, ctx=ctx
                    )
                )
            if scenario.gated_vs_ungated_probe:
                report.probe_outcomes.append(
                    await agent_suite.run_gated_vs_ungated_probe(
                        scenario, registry=DEFAULT_REGISTRY, ctx=ctx
                    )
                )
        # Deliberately not committed — see the docstring above.

    await engine.dispose()

    print(report.render())
    print()
    print("summary_metrics " + json.dumps(report.summary(), sort_keys=True))
    s = report.summary()
    ok = (
        s["allowlist_coverage_ok"] == s["allowlist_coverage_total"]
        and s["pipeline_completed"] == s["pipeline_total"]
        and s["pipeline_forbidden_tool_leaked"] == 0
        and s["probes_where_gate_earned_its_place"] == s["probes_total"]
    )
    return 0 if ok else 1


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
