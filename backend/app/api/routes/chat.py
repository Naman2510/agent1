"""The text conversation turn, streamed over SSE.

Why SSE and not the WebSocket: this is the typed fallback path (accessibility, a noisy room, a
browser without microphone permission). The voice path is a WebSocket carrying audio both ways and
arrives in Phase 3. One-directional token streaming does not need a socket.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import ConversationServiceDep, CurrentUserDep, DbDep, rate_limit_ai
from app.core.errors import NotFoundError
from app.db.repositories.sessions import SessionRepository
from app.schemas.chat import TextTurnRequest, TurnSummary

router = APIRouter(prefix="/sessions", tags=["conversation"])
log = structlog.get_logger(__name__)


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.post(
    "/{session_id}/messages",
    dependencies=[Depends(rate_limit_ai)],
    response_class=StreamingResponse,
)
async def create_text_turn(
    session_id: uuid.UUID,
    payload: TextTurnRequest,
    request: Request,
    current: CurrentUserDep,
    db: DbDep,
    conversation: ConversationServiceDep,
) -> StreamingResponse:
    student_id = current.require_student_id()
    session = await SessionRepository(db).get_for_student(session_id, student_id)
    if session is None:
        # 404 for absent and for not-yours alike; distinguishing them confirms another student's
        # session exists.
        raise NotFoundError("Session not found.")

    async def events() -> AsyncIterator[str]:
        try:
            async for fragment, result in conversation.stream_turn(
                session_id=session_id, student_id=student_id, utterance=payload.text
            ):
                if fragment:
                    yield _sse("delta", {"text": fragment})
                elif result is not None:
                    summary = TurnSummary(
                        turn_index=result.turn_index,
                        stop_reason=result.stop_reason,
                        interrupted=result.interrupted,
                        language=result.language,
                        latency_ms=result.latency_ms,
                        estimated_cost_usd=round(result.cost.cost_usd if result.cost else 0.0, 6),
                        token_usage=result.cost.usage.as_dict() if result.cost else {},
                    )
                    yield _sse("done", summary.model_dump())
            # The DB work for this turn happened inside the service; commit it before the
            # response ends, because the request-scoped transaction is not aware of the stream.
            await db.commit()
        except Exception as exc:
            # Headers are long gone, so an exception cannot become a 500. Report it as a terminal
            # event the client can act on, and log the detail server-side.
            await db.rollback()
            log.error("chat.stream_failed", error_type=type(exc).__name__, exc_info=True)
            yield _sse(
                "error",
                {
                    "code": getattr(exc, "code", "internal_error"),
                    "message": getattr(exc, "message", "The turn could not be completed."),
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Proxies that buffer would defeat the point of streaming.
            "X-Accel-Buffering": "no",
        },
    )
