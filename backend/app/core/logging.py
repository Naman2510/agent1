"""Structured logging with request correlation (ARCHITECTURE §14).

Two rules are enforced here rather than left to call sites:
  1. Secrets never serialise, whatever a caller passes.
  2. Transcripts are hashed unless explicitly enabled in development.
"""

import hashlib
import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.typing import Processor

from app.core.config import Settings

_REDACT_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "jwt_secret",
        "secret",
        "cookie",
    }
)
_TRANSCRIPT_KEYS = frozenset({"transcript", "text", "utterance", "content", "response_text"})


def _redact(_logger: Any, _name: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if key.lower() in _REDACT_KEYS:
            event[key] = "[redacted]"
    return event


def hash_text(text: str) -> str:
    """Stable short digest, so the same utterance is recognisable across log lines."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _transcript_policy(log_transcripts: bool) -> Processor:
    def processor(
        _logger: Any, _name: str, event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        if log_transcripts:
            return event
        for key in list(event):
            if key.lower() in _TRANSCRIPT_KEYS and isinstance(event[key], str):
                event[key] = hash_text(event[key])
                event[f"{key}_chars"] = len(event[key])
        return event

    return processor


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, settings.log_level)
    )
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            _transcript_policy(settings.log_transcripts),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
