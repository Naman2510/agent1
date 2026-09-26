"""Context assembly and citation resolution (spec §16, ARCHITECTURE §11).

The load-bearing rule: **a citation is resolved from what was actually retrieved this turn, never
from what the model says.** The context builder assigns each retrieved chunk a short reference ID
(`[1]`, `[2]`, ...) local to this turn; the model is instructed to cite those IDs; the resolver
looks each cited ID up in *this turn's* retrieved set and drops anything that is not there. A model
cannot fabricate a citation that survives this step, because fabricating one means inventing an ID
that was never issued, and an unissued ID resolves to nothing.

This is also why citation IDs are **not** stable across turns or sessions: reusing "[1]" for a
different chunk next turn would let a stale ID from an earlier answer masquerade as a citation to
different material. Scoped to a turn, never persisted as an identifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.retrieve import RetrievedChunk

# A voice answer is short by design (the persona forbids long answers), so the context budget is
# modest — this is a token *ceiling* the assembler enforces, not a target it aims for.
DEFAULT_MAX_CONTEXT_CHARS = 6000


_CITED_REF = re.compile(r"\[(\d+)\]")
_SPOKEN_REF = re.compile(r"\s*\[\d+\]")


@dataclass(frozen=True)
class ContextBlock:
    """What goes into the prompt: the reference text plus the ID→source map for citation
    resolution. `text` is what the LLM sees; `sources` never is — it stays server-side."""

    text: str
    sources: dict[str, RetrievedChunk]

    @property
    def is_empty(self) -> bool:
        return not self.sources


@dataclass(frozen=True)
class Citation:
    ref: str
    document_title: str
    heading_path: str | None
    section: str | None
    page_start: int | None
    page_end: int | None

    def format(self) -> str:
        """Human-readable form for spec §16's citation display."""
        parts = [self.document_title]
        if self.section:
            parts.append(f"Section: {self.section}")
        elif self.heading_path:
            parts.append(self.heading_path)
        if self.page_start is not None:
            page = (
                f"Page {self.page_start}"
                if self.page_start == self.page_end or self.page_end is None
                else f"Pages {self.page_start}-{self.page_end}"
            )
            parts.append(page)
        return " — ".join(parts)


def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    start_index: int = 1,
) -> ContextBlock:
    """Assemble retrieved chunks into one labelled block, deduplicating and budget-capped.

    Deduplication is by document + heading path: hybrid retrieval's two arms can surface the same
    section, and citing it twice under two different numbers would look like two independent
    sources agreeing when they are one.

    `start_index` continues numbering from a previous call's last ref, so a turn with two
    `search_knowledge` calls gets `[1]`, `[2]`, `[3]`... rather than each call restarting at
    `[1]` — which would leave "[1]" ambiguous between two different sources in the same turn
    (Phase 6: the orchestrator threads one running counter across every call in a turn).
    """
    seen: set[tuple[str, str | None]] = set()
    sources: dict[str, RetrievedChunk] = {}
    parts: list[str] = []
    used_chars = 0

    for chunk in chunks:
        key = (chunk.document_id, chunk.heading_path)
        if key in seen:
            continue
        seen.add(key)

        ref = f"[{start_index + len(sources)}]"
        heading = f" ({chunk.heading_path})" if chunk.heading_path else ""
        entry = f'{ref} From "{chunk.document_title}"{heading}:\n{chunk.content}'

        if used_chars + len(entry) > max_chars and sources:
            # At least one source is always included even if it alone exceeds the budget — an
            # empty context because the single best match was too long would be worse than one
            # over-length source.
            break

        sources[ref] = chunk
        parts.append(entry)
        used_chars += len(entry)

    return ContextBlock(text="\n\n".join(parts), sources=sources)


def resolve_citations(cited_refs: list[str], context: ContextBlock) -> list[Citation]:
    """Turn the model's cited reference IDs into real citations.

    Any ref not in `context.sources` — the model invented it, mistyped it, or is citing a ref from
    a previous turn — is silently dropped. Not raised as an error: a hallucinated citation number
    embedded in otherwise-fine prose should not fail the whole turn, but it must never reach the
    student framed as a real source (spec §16: "Do not fabricate citations").
    """
    citations = []
    for ref in cited_refs:
        chunk = context.sources.get(ref)
        if chunk is None:
            continue
        citations.append(
            Citation(
                ref=ref,
                document_title=chunk.document_title,
                heading_path=chunk.heading_path,
                section=chunk.section,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
        )
    return citations


def extract_cited_refs(text: str) -> list[str]:
    """Pull `[1]`-style references out of the model's answer text, in order of first appearance,
    deduplicated. A tiny, deliberately dumb parser: the format is one the assembler itself defines
    and instructs the model to use, so it does not need to handle arbitrary bracket syntax."""
    seen: list[str] = []
    for match in _CITED_REF.finditer(text):
        ref = f"[{match.group(1)}]"
        if ref not in seen:
            seen.append(ref)
    return seen


def strip_cited_refs(text: str) -> str:
    """The answer as it is *spoken*: every reference `extract_cited_refs` would find, removed with
    the space before it, so "sum to zero [1]." is read as "sum to zero." The sources reach the
    student on screen (the `rag.citations` frame) rather than as numbers read aloud."""
    return _SPOKEN_REF.sub("", text)
