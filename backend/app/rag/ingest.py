"""Document ingestion: parse → clean → chunk → embed → store (ARCHITECTURE §11).

Markdown and plain text are read directly; PDF goes through `pypdf` first. Cleaning is
deliberately minimal and named for what it actually does — dehyphenating line-wrapped words and
collapsing excess whitespace — rather than claimed as a general document-cleaning solution it
is not.

Metadata (`subject`, `topic`, `difficulty`, `semester`) is supplied by the caller at ingestion
time, not inferred from the text: guessing a course's semester from its content would be a
confident-sounding fabrication for a low-value convenience (spec §15's metadata fields are exactly
the fields an admin uploading a document already knows).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from app.agent.lang.script import Script, profile
from app.rag.chunking import Chunk, chunk_markdown

_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


def clean_text(raw: str) -> str:
    """Dehyphenate line-wrapped words and collapse excess whitespace. Nothing more."""
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", raw)
    text = _TRAILING_SPACE.sub("\n", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def parse_pdf(path: Path) -> str:
    """Extract text page by page, joined with page-break markers.

    Page boundaries are kept as literal markers rather than discarded, because `page_start` /
    `page_end` on each chunk (spec §15, citations in spec §16) need to be derived from them.
    """
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\f".join(pages)  # form-feed: an unambiguous, content-safe page separator


def parse_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix in {".md", ".markdown", ".txt"}:
        return path.read_text(encoding="utf-8")
    raise ValueError(f"unsupported document type: {suffix}")


def source_hash(raw_bytes: bytes) -> str:
    """Content hash used for ingestion idempotency (DATA_MODEL.md §5)."""
    return hashlib.sha256(raw_bytes).hexdigest()


@dataclass(frozen=True)
class DocumentMetadata:
    title: str
    subject: str
    topic: str | None = None
    semester: int | None = None
    language: str = "en"
    license: str | None = None
    difficulty: str | None = None


@dataclass(frozen=True)
class PreparedChunk:
    chunk: Chunk
    language: str
    difficulty: str | None


@dataclass(frozen=True)
class PreparedDocument:
    metadata: DocumentMetadata
    source_hash: str
    chunks: list[PreparedChunk] = field(default_factory=list)


def prepare_document(
    path: Path, metadata: DocumentMetadata, *, difficulty_override: str | None = None
) -> PreparedDocument:
    """Parse, clean, and chunk one file. Does not touch the database or an embedder.

    Kept pure and synchronous so it is trivial to unit test: given a file, what chunks result is
    a deterministic function of the file and the chunking parameters, with no I/O beyond the read.
    """
    raw = path.read_bytes()
    text = clean_text(parse_document(path))
    chunks = chunk_markdown(text)

    prepared = [
        PreparedChunk(
            chunk=chunk,
            # Per-chunk language, not the document's declared language: a mostly-English document
            # can have a Hindi-script example embedded in one section, and metadata filtering by
            # language (spec §15) needs the chunk-level truth.
            language=_script_label(chunk.content),
            difficulty=difficulty_override or metadata.difficulty,
        )
        for chunk in chunks
    ]
    return PreparedDocument(metadata=metadata, source_hash=source_hash(raw), chunks=prepared)


def _script_label(text: str) -> str:
    script = profile(text).script
    return {
        Script.DEVANAGARI: "hi",
        Script.TAMIL: "ta",
        Script.LATIN: "en",
    }.get(script, "en")
