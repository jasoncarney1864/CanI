"""Section-aligned, no-overlap chunking for statute text (docs/20-public-law-corpus-design.md
§20.5.5). Deliberately different from cani_shared.chunking: section boundaries are known
exactly (the fetcher already segmented the source into LawSections), so there is nothing to
guess — and no overlap, because a chunk that straddles two sections could get a quote
attributed to the wrong citation, which the product's verbatim-quote guarantee (§20.1
principle 1) cannot tolerate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cani_shared.chunking import TARGET_MAX_TOKENS, _count_tokens
from cani_shared.law.models import LawSection

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:])\s+")


@dataclass
class LawChunk:
    citation: str
    heading: str | None
    text: str
    source_url: str
    chunk_index: int  # document order across the whole source's chunks
    token_count: int
    part: int  # 0-indexed position within the section; >0 only for oversized splits


def _split_oversized_line(line: str) -> list[str]:
    """Last-resort split for a single subsection line that alone exceeds the token budget
    (no natural subsection boundary to split at within it) — packs whole sentences instead,
    still without overlap. NRS 116 sections don't currently hit this path (subsection
    markers keep individual lines short), but a single dense paragraph elsewhere should
    degrade gracefully rather than produce one oversized chunk."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(line) if s]
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = _count_tokens(sentence)
        if current and current_tokens + sentence_tokens > TARGET_MAX_TOKENS:
            parts.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        parts.append(" ".join(current))
    return parts or [line]


def _split_section_text(text: str) -> list[str]:
    """Split section text at subsection-line boundaries only — text.split('\\n') is exact
    here because LawSection.text joins subsection paragraphs ('1. ...', '(a) ...') with '\\n'
    (see sources/nrs.py), so a line boundary IS a subsection boundary."""
    if _count_tokens(text) <= TARGET_MAX_TOKENS:
        return [text]

    lines = text.split("\n")
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for line in lines:
        line_tokens = _count_tokens(line)
        if line_tokens > TARGET_MAX_TOKENS:
            if current:
                parts.append("\n".join(current))
                current, current_tokens = [], 0
            parts.extend(_split_oversized_line(line))
            continue
        if current and current_tokens + line_tokens > TARGET_MAX_TOKENS:
            parts.append("\n".join(current))
            current, current_tokens = [], 0
        current.append(line)
        current_tokens += line_tokens
    if current:
        parts.append("\n".join(current))
    return parts


def chunk_sections(sections: list[LawSection]) -> list[LawChunk]:
    """Map LawSections to chunks in document order. One section -> one chunk unless it
    exceeds TARGET_MAX_TOKENS, in which case it splits at subsection-line boundaries (never
    mid-line, never across a section) with no overlap."""
    chunks: list[LawChunk] = []
    chunk_index = 0
    for section in sections:
        for part, part_text in enumerate(_split_section_text(section.text)):
            chunks.append(
                LawChunk(
                    citation=section.citation,
                    heading=section.heading,
                    text=part_text,
                    source_url=section.source_url,
                    chunk_index=chunk_index,
                    token_count=_count_tokens(part_text),
                    part=part,
                )
            )
            chunk_index += 1
    return chunks
