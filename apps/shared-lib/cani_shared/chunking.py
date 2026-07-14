"""Hybrid structural + token chunking per docs/08-rag-pipeline-design.md §8.6:
target ~600-900 tokens with 80-120 token overlap, prefer section-based splits when
headings are detected, never mix content from different documents in one chunk (trivially
true here since chunk_document operates on a single document's pages only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

TARGET_MIN_TOKENS = 600
TARGET_MAX_TOKENS = 900
OVERLAP_TOKENS = 100

_ENCODING = tiktoken.get_encoding("cl100k_base")

_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:[A-Z][A-Z \-/]{3,60}|(?:Section\s+)?\d{1,2}(?:\.\d{1,2})*[.)]\s+\S.{0,80})\s*$"
)


@dataclass
class PageText:
    page_number: int
    text: str


@dataclass
class Chunk:
    text: str
    page_start: int
    page_end: int
    section_label: str | None
    chunk_index: int
    token_count: int


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _split_lines_with_pages(pages: list[PageText]) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for page in pages:
        for line in page.text.splitlines():
            if line.strip():
                lines.append((page.page_number, line))
    return lines


def chunk_document(pages: list[PageText]) -> list[Chunk]:
    lines = _split_lines_with_pages(pages)
    chunks: list[Chunk] = []
    current_lines: list[tuple[int, str]] = []
    current_section: str | None = None
    chunk_index = 0

    def flush(next_section_start: list[tuple[int, str]] | None = None) -> None:
        nonlocal chunk_index, current_lines
        if not current_lines:
            return
        text = "\n".join(line for _, line in current_lines)
        token_count = _count_tokens(text)
        page_start = current_lines[0][0]
        page_end = current_lines[-1][0]
        chunks.append(
            Chunk(
                text=text,
                page_start=page_start,
                page_end=page_end,
                section_label=current_section,
                chunk_index=chunk_index,
                token_count=token_count,
            )
        )
        chunk_index += 1
        if next_section_start is not None:
            current_lines = next_section_start
        else:
            # Carry forward an overlap tail so retrieval doesn't lose context at chunk
            # boundaries; approximate by token budget rather than exact line slicing.
            overlap: list[tuple[int, str]] = []
            overlap_tokens = 0
            for page_no, line in reversed(current_lines):
                overlap_tokens += _count_tokens(line)
                overlap.insert(0, (page_no, line))
                if overlap_tokens >= OVERLAP_TOKENS:
                    break
            current_lines = overlap

    for page_no, line in lines:
        if _SECTION_HEADING_RE.match(line):
            if current_lines and _count_tokens("\n".join(t for _, t in current_lines)) >= TARGET_MIN_TOKENS // 2:
                flush(next_section_start=[])
            current_section = line.strip()
            current_lines.append((page_no, line))
            continue

        current_lines.append((page_no, line))
        running_tokens = _count_tokens("\n".join(t for _, t in current_lines))
        if running_tokens >= TARGET_MAX_TOKENS:
            flush()

    flush(next_section_start=[])
    return [c for c in chunks if c.text.strip()]
