"""Structure-aware chunking (ARCHITECTURE §11)."""

from __future__ import annotations

from app.rag.chunking import chunk_markdown, embed_text, parse_sections

DOC = """\
# Unit 3: Circuit Fundamentals

## Chapter 7: Kirchhoff's Laws

### 7.1 Kirchhoff's Voltage Law

KVL says the sum of voltages around a loop is zero.

### 7.2 Kirchhoff's Current Law

KCL says the sum of currents at a node is zero.
"""


def test_headings_build_a_nested_path() -> None:
    sections = parse_sections(DOC)
    assert [s.path_str for s in sections] == [
        "Unit 3: Circuit Fundamentals > Chapter 7: Kirchhoff's Laws > 7.1 Kirchhoff's Voltage Law",
        "Unit 3: Circuit Fundamentals > Chapter 7: Kirchhoff's Laws > 7.2 Kirchhoff's Current Law",
    ]


def test_a_sibling_heading_does_not_keep_the_previous_leaf() -> None:
    """Moving from 7.1 to 7.2 must replace the leaf, not append to it."""
    sections = parse_sections(DOC)
    assert sections[1].leaf == "7.2 Kirchhoff's Current Law"
    assert "7.1" not in sections[1].path_str


def test_returning_to_a_shallower_level_drops_the_deeper_path() -> None:
    text = "# A\n\n## A.1\n\ndeep text\n\n# B\n\nshallow text\n"
    sections = parse_sections(text)
    assert sections[-1].path_str == "B"
    assert "A.1" not in sections[-1].path_str


def test_a_short_section_stays_whole() -> None:
    chunks = chunk_markdown(DOC)
    assert len(chunks) == 2
    assert "KVL says" in chunks[0].content
    assert "KCL says" in chunks[1].content


def test_each_chunk_carries_its_heading_path_and_leaf_section() -> None:
    chunks = chunk_markdown(DOC)
    assert chunks[0].heading_path.endswith("7.1 Kirchhoff's Voltage Law")
    assert chunks[0].section == "7.1 Kirchhoff's Voltage Law"


def test_a_long_section_is_split_at_paragraph_boundaries() -> None:
    paragraphs = [
        f"Paragraph {i} with some real sentence content to pad length out." for i in range(40)
    ]
    long_doc = "# Long\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_markdown(long_doc, target_tokens=50, max_tokens=60, overlap_tokens=10)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 70, "a split chunk must respect target, with only small overrun"


def test_a_long_section_split_never_breaks_inside_a_paragraph() -> None:
    """The split unit is a whole paragraph — cutting mid-paragraph would separate related
    sentences for no benefit, per ARCHITECTURE §11."""
    paragraphs = [f"This is paragraph number {i}, complete and self-contained." for i in range(20)]
    long_doc = "# Long\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_markdown(long_doc, target_tokens=30, max_tokens=40, overlap_tokens=5)
    for chunk in chunks:
        for paragraph in paragraphs:
            assert paragraph not in chunk.content or chunk.content.count(paragraph) == 1


def test_overlap_carries_context_across_a_split() -> None:
    paragraphs = [
        f"Sentence {i} about waveguides and cutoff frequency behaviour here." for i in range(30)
    ]
    long_doc = "# Long\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_markdown(long_doc, target_tokens=40, max_tokens=50, overlap_tokens=15)
    assert len(chunks) >= 2
    # The overlap means consecutive chunks share at least one paragraph's text.
    shared = set(chunks[0].content.split("\n\n")) & set(chunks[1].content.split("\n\n"))
    assert shared, "no context carried across the split"


def test_no_text_is_lost_across_a_split() -> None:
    paragraphs = [f"Unique marker sentence number {i} here." for i in range(25)]
    long_doc = "# Long\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_markdown(long_doc, target_tokens=30, max_tokens=40, overlap_tokens=0)
    all_text = " ".join(c.content for c in chunks)
    for paragraph in paragraphs:
        assert paragraph in all_text


def test_a_document_with_no_headings_is_still_chunked() -> None:
    chunks = chunk_markdown("Just a paragraph with no heading at all, some real content here.")
    assert len(chunks) == 1
    assert chunks[0].heading_path == ""


def test_blank_sections_produce_no_chunk() -> None:
    text = "# Empty section\n\n\n\n# Real section\n\nActual content here.\n"
    chunks = chunk_markdown(text)
    assert len(chunks) == 1
    assert "Real section" in chunks[0].heading_path


def test_embed_text_prefixes_the_heading_path() -> None:
    """The 'large, cheap retrieval win' ARCHITECTURE §11 describes."""
    chunks = chunk_markdown(DOC)
    embedded = embed_text(chunks[1])
    assert embedded.startswith(chunks[1].heading_path)
    assert "KCL says" in embedded


def test_embed_text_with_no_heading_path_returns_content_unchanged() -> None:
    chunks = chunk_markdown("Just a paragraph, no heading.")
    assert embed_text(chunks[0]) == chunks[0].content
