"""Each suite, run from a config, returning one `SuiteOutcome` shape (eval/recording.py).

The suites' own logic stays in `eval/suites/`; this module decides what each one reads (its
dataset files, which the run's digest covers), which knobs it takes, and what a case record holds.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eval.recording import CaseRecord, ConfigError, SuiteOutcome, files_under
from eval.suites import agent as agent_suite
from eval.suites import injection as injection_suite
from eval.suites import lid as lid_suite
from eval.suites import retrieval as retrieval_suite

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True)
class Suite:
    name: str
    measures: str
    needs_database: bool
    dataset_files: Callable[[Path], list[Path]]
    evaluate: Callable[[dict[str, Any], Path, bool, Settings | None], Awaitable[SuiteOutcome]]


def _database(settings: Settings | None) -> Settings:
    if settings is None:
        raise ConfigError("this suite needs a database; the runner supplies its settings")
    return settings


# --- lid ---------------------------------------------------------------------


def _lid_files(dataset: Path) -> list[Path]:
    return [dataset / "lid" / "cases.jsonl"]


async def _evaluate_lid(
    config: dict[str, Any], dataset: Path, show_failures: bool, settings: Settings | None
) -> SuiteOutcome:
    cases = lid_suite.load_cases(dataset / "lid" / "cases.jsonl")
    result = lid_suite.run(cases)

    lines = [
        "SIGNAL — did the utterance itself identify its language?",
        "(no usable signal counts as `unknown`, even where the router then answered correctly)",
        "",
        result.signal.render(),
        "",
        "ROUTED — what the router actually chose, sticky prior included",
        "(closer to what a student experiences; a fresh session defaults to English)",
        "",
        result.routed.render(),
    ]
    failures = [o for o in result.outcomes if not o.passed]
    if show_failures and failures:
        lines += ["", f"failures ({len(failures)})"]
        for outcome in failures:
            lines.append(
                f"  {outcome.case.id:10s} expected {outcome.case.language:8s} "
                f"got {outcome.predicted:8s} | {outcome.case.text}"
            )
            lines.append(f"             {outcome.explanation}")

    return SuiteOutcome(
        summary={"signal": result.signal.summary(), "routed": result.routed.summary()},
        cases=[
            CaseRecord(
                case_id=o.case.id,
                passed=o.passed,
                language=o.case.language,
                input={"text": o.case.text, "difficulty": o.case.difficulty},
                expected={"language": o.case.language},
                actual={"language": o.predicted},
                notes=o.explanation,
            )
            for o in result.outcomes
        ],
        report="\n".join(lines),
        ok=True,
    )


# --- retrieval ---------------------------------------------------------------

RETRIEVAL_MODES = {
    "hybrid": (True, True),
    "vector_only": (True, False),
    "lexical_only": (False, True),
}


def _retrieval_files(dataset: Path) -> list[Path]:
    return [dataset / "retrieval" / "cases.jsonl", *files_under(dataset / "corpus")]


async def _evaluate_retrieval(
    config: dict[str, Any], dataset: Path, show_failures: bool, settings: Settings | None
) -> SuiteOutcome:
    """Ingests the dataset's corpus afresh, under this config, inside a transaction that is rolled
    back — so the result depends on the dataset and the config alone, whatever the database held
    before, and nothing is left behind. (Other writers to the corpus tables wait for the run.)"""
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import Document, DocumentChunk
    from app.db.session import create_engine
    from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
    from app.providers.reranker.base import NoopReranker
    from app.rag.ingest import load_corpus_manifest
    from app.rag.service import RagService

    mode = config.get("retrieval", {}).get("mode", "hybrid")
    if mode not in (*RETRIEVAL_MODES, "bm25_reference"):
        raise ConfigError(f"unknown retrieval mode {mode!r}")
    heading_prefix = bool(config.get("embedding", {}).get("heading_prefix", True))

    cases = retrieval_suite.load_cases(dataset / "retrieval" / "cases.jsonl")
    corpus = load_corpus_manifest(dataset / "corpus" / "documents.json")

    engine = create_engine(_database(settings))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            await session.execute(delete(Document))
            embeddings = TfidfSvdEmbeddingProvider()
            rag = RagService(
                session,
                embeddings=embeddings,
                reranker=NoopReranker(),
                heading_prefix=heading_prefix,
            )
            for path, metadata in corpus:
                await rag.ingest_file(path, metadata)
            chunk_count = await rag.fit_and_embed_all()

            async def run(subset: list[retrieval_suite.RetrievalCase]) -> Any:
                if mode == "bm25_reference":
                    return await retrieval_suite.run_bm25_offline(session, subset)
                use_vector, use_lexical = RETRIEVAL_MODES[mode]
                return await retrieval_suite.run_config(
                    session,
                    subset,
                    embeddings=embeddings,
                    use_vector=use_vector,
                    use_lexical=use_lexical,
                )

            report = await run(cases)
            by_language: dict[str, Any] = {}
            for language in sorted({case.language for case in cases}):
                subset = [case for case in cases if case.language == language]
                by_language[language] = {"n": len(subset), **(await run(subset)).summary()}

            # Chunk ids are regenerated by every ingest; a case record names chunks by where they
            # are, which is stable across runs and readable in a failure browser.
            rows = await session.execute(
                select(DocumentChunk.id, DocumentChunk.heading_path, Document.title).join(
                    Document, Document.id == DocumentChunk.document_id
                )
            )
            names = {str(r.id): f"{r.title} > {r.heading_path or '(top)'}" for r in rows}
            embedder = embeddings.info.model
        finally:
            await session.rollback()
    await engine.dispose()

    by_query = {case.id: case for case in cases}
    records = []
    for metric in report.per_query:
        case = by_query[metric.query_id]
        records.append(
            CaseRecord(
                case_id=metric.query_id,
                passed=metric.recall_at_k.get(10, 0.0) > 0.0,
                language=case.language,
                input={"query": case.query, "filters": case.filters or {}},
                expected={"relevant": sorted(names[i] for i in metric.relevant if i in names)},
                actual={"top10": [names.get(i, i) for i in metric.returned[:10]]},
                metrics={
                    **{f"recall@{k}": v for k, v in metric.recall_at_k.items()},
                    "mrr": metric.mrr,
                    "ndcg@10": metric.ndcg_at_10,
                },
            )
        )

    lines = [
        f"mode             {mode}",
        f"embedder         {embedder}",
        f"chunks           {chunk_count}",
    ]
    lines += ["", report.render(), "", "per language"]
    for language, s in by_language.items():
        lines.append(
            f"  {language:8s} n={s['n']:3d}  recall@5 {s['recall@5']:.3f}  "
            f"recall@10 {s['recall@10']:.3f}  mrr {s['mrr']:.3f}  ndcg@10 {s['ndcg@10']:.3f}"
        )
    if show_failures:
        misses = [r for r in records if not r.passed]
        lines += ["", f"misses — nothing relevant in the top 10 ({len(misses)})"]
        lines += [f"  {r.case_id}: {r.input['query']}" for r in misses]

    return SuiteOutcome(
        summary={**report.summary(), "by_language": by_language, "chunks": chunk_count},
        cases=records,
        report="\n".join(lines),
        ok=True,
    )


# --- agent and injection -----------------------------------------------------


def _agent_files(dataset: Path) -> list[Path]:
    return [dataset / "agent" / "scenarios.jsonl"]


def _injection_files(dataset: Path) -> list[Path]:
    return [dataset / "agent" / "injection_cases.jsonl"]


async def _with_student(
    work: Callable[[Any, Any, Any], Awaitable[Any]], settings: Settings | None
) -> Any:
    """Run `work` with a student inside a transaction that is never committed: these suites
    succeed by changing nothing, so there is nothing worth keeping, and a shared database keeps
    no trace of them."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import Student, User, UserRole
    from app.db.session import create_engine

    engine = create_engine(_database(settings))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            try:
                user = User(
                    email="eval-suite@example.invalid",
                    password_hash="x",  # noqa: S106 - a throwaway actor that is never committed
                    role=UserRole.STUDENT,
                )
                session.add(user)
                await session.flush()
                student = Student(user_id=user.id, display_name="eval-suite")
                session.add(student)
                await session.flush()
                return await work(session, user, student)
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def _tool_context(session: Any, student: Any, conversation_session: Any) -> Any:
    from app.agent.tools.base import ToolContext
    from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
    from app.providers.reranker.base import NoopReranker
    from app.rag.service import RagService

    rag = RagService(session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker())
    return ToolContext(
        student_id=student.id,
        session_id=conversation_session.id,
        turn_index=0,
        db=session,
        rag=rag,
        citation_sources={},
    )


async def _evaluate_injection(
    config: dict[str, Any], dataset: Path, show_failures: bool, settings: Settings | None
) -> SuiteOutcome:
    from app.agent.tools.registry import DEFAULT_REGISTRY
    from app.db.models import Session

    cases = injection_suite.load_cases(dataset / "agent" / "injection_cases.jsonl")

    async def work(session: Any, _user: Any, student: Any) -> Any:
        conversation_session = Session(student_id=student.id, transport="text")
        session.add(conversation_session)
        await session.flush()
        ctx = _tool_context(session, student, conversation_session)
        return await injection_suite.run(cases, registry=DEFAULT_REGISTRY, ctx=ctx)

    report = await _with_student(work, settings)
    by_case = {case.id: case for case in cases}
    records = [
        CaseRecord(
            case_id=f"{outcome.case_id}:{index}:{outcome.tool}",
            passed=outcome.blocked,
            input={
                "category": by_case[outcome.case_id].category,
                "injection_site": by_case[outcome.case_id].injection_site,
                "tool": outcome.tool,
            },
            expected={"defense": str(outcome.expected_defense)},
            actual={"blocked": outcome.blocked, "message": outcome.message},
        )
        for index, outcome in enumerate(report.outcomes)
    ]
    return SuiteOutcome(
        summary=report.summary(), cases=records, report=report.render(), ok=not report.executed
    )


async def _evaluate_agent(
    config: dict[str, Any], dataset: Path, show_failures: bool, settings: Settings | None
) -> SuiteOutcome:
    from app.agent.tools.registry import DEFAULT_REGISTRY
    from app.db.models import Session

    scenarios = agent_suite.load_cases(dataset / "agent" / "scenarios.jsonl")
    report = agent_suite.AgentReport()
    for scenario in scenarios:
        report.allowlist_checks.append(agent_suite.check_allowlist_coverage(scenario))

    async def work(session: Any, _user: Any, student: Any) -> None:
        for scenario in scenarios:
            conversation_session = Session(student_id=student.id, transport="text")
            session.add(conversation_session)
            await session.flush()
            ctx = _tool_context(session, student, conversation_session)
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

    await _with_student(work, settings)

    allowlist = {c.scenario_id: c for c in report.allowlist_checks}
    pipeline = {o.scenario_id: o for o in report.pipeline_outcomes}
    probes = {o.scenario_id: o for o in report.probe_outcomes}
    records = []
    for scenario in scenarios:
        check = allowlist[scenario.id]
        run = pipeline.get(scenario.id)
        probe = probes.get(scenario.id)
        passed = (
            check.ok
            and (run is None or (run.completed and not run.forbidden_tools_executed))
            and (probe is None or (probe.gated_blocked_it and probe.ungated_executed_it))
        )
        records.append(
            CaseRecord(
                case_id=scenario.id,
                passed=passed,
                input={"utterance": scenario.utterance, "intent": scenario.intent_context},
                expected={
                    "tools": scenario.expected_tools,
                    "forbidden": scenario.forbidden_tools,
                },
                actual={
                    "allowlist_ok": check.ok,
                    "executed": sorted(run.executed_tools) if run else None,
                    "forbidden_executed": sorted(run.forbidden_tools_executed) if run else None,
                    "probe_gated_blocked": probe.gated_blocked_it if probe else None,
                },
            )
        )
    s = report.summary()
    ok = (
        s["allowlist_coverage_ok"] == s["allowlist_coverage_total"]
        and s["pipeline_completed"] == s["pipeline_total"]
        and s["pipeline_forbidden_tool_leaked"] == 0
        and s["probes_where_gate_earned_its_place"] == s["probes_total"]
    )
    return SuiteOutcome(summary=s, cases=records, report=report.render(), ok=ok)


SUITES: dict[str, Suite] = {
    "lid": Suite(
        "lid",
        "the language router on text: lexicon and script, no model",
        False,
        _lid_files,
        _evaluate_lid,
    ),
    "retrieval": Suite(
        "retrieval",
        "the production retriever over the dataset's corpus, ingested afresh for the run",
        True,
        _retrieval_files,
        _evaluate_retrieval,
    ),
    "agent": Suite(
        "agent",
        "allowlist coverage and real pipeline execution under a scripted model — not a real "
        "model's tool-selection accuracy",
        True,
        _agent_files,
        _evaluate_agent,
    ),
    "injection": Suite(
        "injection",
        "whether a model already persuaded by injected text is still blocked before mutating "
        "anything — not whether a real model resists the injection",
        True,
        _injection_files,
        _evaluate_injection,
    ),
}
