"""Document parsing and cleaning. No database — `prepare_document` is pure I/O plus computation."""

from __future__ import annotations

import hashlib

import pytest

from app.rag.ingest import DocumentMetadata, clean_text, prepare_document, source_hash


def test_hyphenated_line_wraps_are_rejoined() -> None:
    assert clean_text("wave-\nguide") == "waveguide"


def test_ordinary_hyphens_are_not_touched() -> None:
    """Only a hyphen immediately followed by a line break is a wrap artefact; a real compound
    word's hyphen must survive."""
    assert clean_text("well-known result") == "well-known result"


def test_trailing_whitespace_is_stripped_from_lines() -> None:
    assert clean_text("line one   \nline two\t\n") == "line one\nline two"


def test_excess_blank_lines_are_collapsed_to_one() -> None:
    assert clean_text("a\n\n\n\n\nb") == "a\n\nb"


def test_leading_and_trailing_whitespace_is_stripped() -> None:
    assert clean_text("  \n\ntext\n\n  ") == "text"


def test_source_hash_is_deterministic_and_content_sensitive() -> None:
    a = source_hash(b"same content")
    b = source_hash(b"same content")
    c = source_hash(b"different content")
    assert a == b
    assert a != c
    assert a == hashlib.sha256(b"same content").hexdigest()


def test_prepare_document_chunks_a_real_markdown_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "sample.md"
    path.write_text(
        "# Unit 1\n\n## 1.1 Topic\n\nSome content about the topic here for testing.\n"
    )
    metadata = DocumentMetadata(title="Sample", subject="Testing", difficulty="easy")
    prepared = prepare_document(path, metadata)

    assert prepared.metadata.title == "Sample"
    assert len(prepared.chunks) == 1
    assert prepared.chunks[0].language == "en"
    assert prepared.chunks[0].difficulty == "easy"
    assert prepared.source_hash == source_hash(path.read_bytes())


def test_per_chunk_language_reflects_the_chunks_own_script_not_the_document_default(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """A mostly-English document can have one Hindi-script section; metadata filtering by
    language (spec §15) needs the chunk-level truth, not the document's declared default."""
    path = tmp_path / "mixed.md"
    path.write_text(
        "# Doc\n\n## English section\n\nThis is written in English throughout.\n\n"
        "## हिंदी खंड\n\nयह पूरा खंड हिंदी में लिखा गया है और इसमें पर्याप्त शब्द हैं।\n"
    )
    prepared = prepare_document(path, DocumentMetadata(title="Mixed", subject="Testing"))
    languages = {c.chunk.heading_path: c.language for c in prepared.chunks}
    assert any(lang == "en" for lang in languages.values())
    assert any(lang == "hi" for lang in languages.values())


def test_difficulty_override_takes_precedence_over_metadata_default(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "doc.md"
    path.write_text("# Doc\n\n## Section\n\nSome content for the test.\n")
    metadata = DocumentMetadata(title="Doc", subject="Testing", difficulty="easy")
    prepared = prepare_document(path, metadata, difficulty_override="hard")
    assert prepared.chunks[0].difficulty == "hard"


def test_an_unsupported_file_type_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "doc.docx"
    path.write_text("content")
    with pytest.raises(ValueError, match="unsupported document type"):
        prepare_document(path, DocumentMetadata(title="Doc", subject="Testing"))


def test_plain_text_files_are_read_directly(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "notes.txt"
    path.write_text("Just some plain text notes about circuits and things.")
    prepared = prepare_document(path, DocumentMetadata(title="Notes", subject="Testing"))
    assert len(prepared.chunks) == 1
    assert "circuits" in prepared.chunks[0].chunk.content
