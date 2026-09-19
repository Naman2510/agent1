"""The `search_knowledge` tool, wired for real (Phase 5 built the pipeline and the schema; this
is the ADR-0009 orchestrator caller the module docstring in `app.rag.tool_spec` anticipated)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from app.agent.tools.base import ToolContext
from app.db.repositories.retrieval_log import RetrievalLogRepository
from app.rag.tool_spec import SEARCH_KNOWLEDGE_TOOL, SearchKnowledgeInput

__all__ = ["SEARCH_KNOWLEDGE_TOOL", "search_knowledge"]


async def search_knowledge(args: SearchKnowledgeInput, ctx: ToolContext) -> dict[str, Any]:
    filters = {
        key: value
        for key, value in (
            ("subject", args.subject),
            ("topic", args.topic),
            ("difficulty", args.difficulty),
        )
        if value is not None
    }

    started = time.perf_counter()
    chunks, context = await ctx.rag.search(
        args.query,
        filters=filters or None,
        citation_start_index=len(ctx.citation_sources) + 1,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    # Merge into the turn-wide registry so the orchestrator can resolve citations against every
    # source retrieved this turn, not just this one call (see ToolContext.citation_sources).
    ctx.citation_sources.update(context.sources)

    await RetrievalLogRepository(ctx.db).record(
        session_id=ctx.session_id,
        query=args.query,
        retriever_config={"filters": filters, "tool": "search_knowledge"},
        candidate_ids=[uuid.UUID(chunk.id) for chunk in chunks],
        chosen_ids=[uuid.UUID(chunk.id) for chunk in context.sources.values()],
        latency_ms=latency_ms,
    )

    if context.is_empty:
        return {
            "found": False,
            "message": "No relevant course material was found for this query.",
        }
    return {"found": True, "context": context.text}
