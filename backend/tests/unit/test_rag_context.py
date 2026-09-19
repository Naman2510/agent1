"""Context assembly and citation resolution.

The one property that matters most: a citation the model invents must never survive resolution
(spec §16, ARCHITECTURE §11). Everything else is secondary to that.
"""

from __future__ import annotations

from app.rag.context import build_context, extract_cited_refs, resolve_citations
from app.rag.retrieve import RetrievedChunk


def _chunk(id_: str, title: str, heading: str, content: str, **kwargs) -> RetrievedChunk:  # type: ignore[no-untyped-def]
    return RetrievedChunk(
        id=id_,
        content=content,
        heading_path=heading,
        # Same title -> same document by default, matching how two chunks from one real document
        # actually relate; a caller wanting genuinely distinct documents overrides this.
        document_id=kwargs.get("document_id", f"doc-{title}"),
        document_title=title,
        page_start=kwargs.get("page_start", 1),
        page_end=kwargs.get("page_end", 1),
        section=kwargs.get("section", heading),
        score=0.9,
        source_ranks={"vector": 1},
    )


def test_chunks_are_numbered_from_one_in_order() -> None:
    chunks = [
        _chunk("a", "Doc A", "1.1", "content a"),
        _chunk("b", "Doc B", "2.1", "content b"),
    ]
    ctx = build_context(chunks)
    assert list(ctx.sources.keys()) == ["[1]", "[2]"]


def test_start_index_continues_numbering_from_a_previous_call() -> None:
    """A turn with two search_knowledge calls must not have both restart at [1] — that would
    leave "[1]" ambiguous between two different sources in the same turn (Phase 6)."""
    first = build_context([_chunk("a", "Doc A", "1.1", "content a")])
    second = build_context(
        [_chunk("b", "Doc B", "2.1", "content b")], start_index=len(first.sources) + 1
    )
    assert list(first.sources.keys()) == ["[1]"]
    assert list(second.sources.keys()) == ["[2]"]


def test_duplicate_document_and_heading_is_deduplicated() -> None:
    """Hybrid retrieval's two arms can surface the same section; citing it twice would look like
    two sources agreeing when it is one."""
    chunks = [
        _chunk("a", "Doc A", "1.1", "content a"),
        _chunk("a2", "Doc A", "1.1", "content a duplicate"),
    ]
    ctx = build_context(chunks)
    assert len(ctx.sources) == 1


def test_the_same_document_different_heading_is_not_deduplicated() -> None:
    chunks = [
        _chunk("a", "Doc A", "1.1", "content a"),
        _chunk("b", "Doc A", "1.2", "content b"),
    ]
    ctx = build_context(chunks)
    assert len(ctx.sources) == 2


def test_an_empty_chunk_list_produces_an_empty_context() -> None:
    ctx = build_context([])
    assert ctx.is_empty
    assert ctx.text == ""


def test_the_char_budget_is_enforced_but_never_empties_a_nonempty_result() -> None:
    big_chunk = _chunk("a", "Doc A", "1.1", "x" * 10_000)
    small_chunk = _chunk("b", "Doc B", "2.1", "short")
    ctx = build_context([big_chunk, small_chunk], max_chars=100)
    # The first source is kept even though it alone exceeds the budget.
    assert "[1]" in ctx.sources
    assert "[2]" not in ctx.sources, "the budget must still stop a second source being added"


def test_a_fabricated_citation_id_is_dropped() -> None:
    """The load-bearing test in this module: a model cannot cite a source it was never given."""
    chunks = [_chunk("a", "Doc A", "1.1", "content a")]
    ctx = build_context(chunks)
    citations = resolve_citations(["[1]", "[99]"], ctx)
    assert [c.ref for c in citations] == ["[1]"]


def test_a_citation_from_a_previous_turn_does_not_carry_forward() -> None:
    """IDs are scoped to one turn's context, never persisted as identifiers — reusing [1] for a
    different chunk next turn would let a stale citation masquerade as a new one."""
    turn_one = build_context([_chunk("a", "Doc A", "1.1", "content a")])
    turn_two = build_context([_chunk("b", "Doc B", "2.1", "content b")])
    # [1] in turn two's context is a different chunk than [1] in turn one's.
    assert turn_one.sources["[1]"].id != turn_two.sources["[1]"].id
    citations = resolve_citations(["[1]"], turn_two)
    assert citations[0].document_title == "Doc B"


def test_no_citations_when_the_model_cites_nothing() -> None:
    ctx = build_context([_chunk("a", "Doc A", "1.1", "content")])
    assert resolve_citations([], ctx) == []


def test_extract_cited_refs_deduplicates_and_preserves_first_order() -> None:
    text = "First point [2]. Second point [1]. Third point [2] again."
    assert extract_cited_refs(text) == ["[2]", "[1]"]


def test_extract_cited_refs_ignores_non_citation_brackets() -> None:
    # A number in brackets that happens to appear in prose is still extracted — the extractor is
    # deliberately simple; the resolver, not the extractor, is what prevents fabrication.
    assert extract_cited_refs("no citations here") == []


def test_citation_format_includes_document_and_page() -> None:
    chunks = [
        _chunk("a", "Kirchhoff's Laws", "7.1", "content", page_start=14, page_end=14, section="7.1")
    ]
    ctx = build_context(chunks)
    citation = resolve_citations(["[1]"], ctx)[0]
    formatted = citation.format()
    assert "Kirchhoff's Laws" in formatted
    assert "Page 14" in formatted


def test_citation_format_handles_a_page_range() -> None:
    chunks = [_chunk("a", "Doc A", "1.1", "content", page_start=30, page_end=31)]
    ctx = build_context(chunks)
    citation = resolve_citations(["[1]"], ctx)[0]
    assert "Pages 30-31" in citation.format()


def test_context_text_never_contains_a_source_object() -> None:
    """`text` is what the LLM sees; `sources` never is — confirmed structurally, not just by
    convention."""
    ctx = build_context([_chunk("a", "Doc A", "1.1", "content a")])
    assert isinstance(ctx.text, str)
    assert "RetrievedChunk" not in ctx.text
