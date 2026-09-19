"""Structure-aware chunking (ARCHITECTURE §11).

Deliberately not "split every 512 tokens": a chunk boundary that ignores document structure can
cut a worked example in half or separate a heading from the paragraph it introduces. Instead,
Markdown headings define section boundaries, and each chunk records the full heading path it sits
under (`Unit 3 > Chapter 7 > 7.1 Kirchhoff's Voltage Law`), which is prepended to the *embedded*
text — a large, cheap retrieval win on lecture-style material, per ARCHITECTURE §11, and it is
also what makes citations human-readable rather than a bare page number.

Token counting is approximate (whitespace-split word count), not a real tokenizer: exactness here
would not change any chunking decision, only the reported count, so a real tokenizer is not worth
the dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

TARGET_TOKENS = 350
OVERLAP_TOKENS = 50
MAX_TOKENS = 500


@dataclass(frozen=True)
class Chunk:
    content: str
    heading_path: str
    section: str | None
    token_count: int


def _approx_tokens(text: str) -> int:
    return len(text.split())


@dataclass
class _Section:
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    lines: list[str] = field(default_factory=list)

    @property
    def path_str(self) -> str:
        return " > ".join(self.heading_path)

    @property
    def leaf(self) -> str | None:
        return self.heading_path[-1] if self.heading_path else None


def parse_sections(markdown: str) -> list[_Section]:
    """Split Markdown into sections at heading boundaries, tracking the full heading path.

    A level-3 heading nests under the most recent level-2 and level-1 headings, and so on; a new
    heading at level k replaces everything at level >= k in the path, which is how the path stays
    correct as the document moves between siblings and back up a level.
    """
    sections: list[_Section] = []
    path: list[str] = []
    current = _Section(heading_path=(), lines=[])

    for line in markdown.splitlines():
        match = HEADING_RE.match(line)
        if match:
            if current.lines and any(line.strip() for line in current.lines):
                sections.append(current)
            level = len(match.group(1))
            title = match.group(2).strip()
            path = path[: level - 1]
            while len(path) < level - 1:
                path.append("")  # a skipped heading level; kept empty rather than guessed
            path.append(title)
            current = _Section(heading_path=tuple(p for p in path if p), lines=[])
        else:
            current.lines.append(line)

    if current.lines and any(line.strip() for line in current.lines):
        sections.append(current)
    return sections


def chunk_markdown(
    markdown: str,
    *,
    target_tokens: int = TARGET_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
    max_tokens: int = MAX_TOKENS,
) -> list[Chunk]:
    """Chunk a Markdown document, respecting section boundaries first and a token target second.

    A section shorter than the target stays whole — splitting a short section for the sake of a
    uniform size would separate related sentences for no benefit. A section longer than
    `max_tokens` is split at paragraph boundaries with a small overlap, so a chunk near a split
    still carries some of the preceding context.
    """
    chunks: list[Chunk] = []
    for section in parse_sections(markdown):
        text = "\n".join(section.lines).strip()
        if not text:
            continue

        if _approx_tokens(text) <= max_tokens:
            chunks.append(
                Chunk(
                    content=text,
                    heading_path=section.path_str,
                    section=section.leaf,
                    token_count=_approx_tokens(text),
                )
            )
            continue

        chunks.extend(
            _split_long_section(
                text,
                heading_path=section.path_str,
                section=section.leaf,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
            )
        )
    return chunks


def _split_long_section(
    text: str, *, heading_path: str, section: str | None, target_tokens: int, overlap_tokens: int
) -> list[Chunk]:
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        if not current:
            return
        body = "\n\n".join(current)
        chunks.append(
            Chunk(
                content=body,
                heading_path=heading_path,
                section=section,
                token_count=_approx_tokens(body),
            )
        )

    for paragraph in paragraphs:
        paragraph_tokens = _approx_tokens(paragraph)
        if current and current_tokens + paragraph_tokens > target_tokens:
            flush()
            # Overlap: carry the tail of the previous chunk forward, by paragraph, until the
            # overlap budget is spent — never mid-paragraph, which would produce a fragment that
            # starts or ends mid-sentence.
            carried: list[str] = []
            carried_tokens = 0
            for prior in reversed(current):
                prior_tokens = _approx_tokens(prior)
                if carried_tokens + prior_tokens > overlap_tokens:
                    break
                carried.insert(0, prior)
                carried_tokens += prior_tokens
            current = carried
            current_tokens = carried_tokens

        current.append(paragraph)
        current_tokens += paragraph_tokens

    flush()
    return chunks


def embed_text(chunk: Chunk) -> str:
    """The text actually handed to the embedder: heading path prefixed onto the content.

    This is the "large, cheap retrieval win" ARCHITECTURE §11 refers to — a query for "waveguide
    impedance" matches a chunk whose own text says only "the wave impedance rises... near cutoff"
    because the prefixed path contributes the word "waveguide".
    """
    if not chunk.heading_path:
        return chunk.content
    return f"{chunk.heading_path}\n\n{chunk.content}"
