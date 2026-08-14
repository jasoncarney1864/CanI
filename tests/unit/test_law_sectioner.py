"""Section-aligned chunker (docs/20 §20.5.5, §20.10): one section -> one chunk when it fits
budget, oversize splits at subsection-line boundaries without overlap, and a split never
crosses a section boundary.
"""

from __future__ import annotations

from cani_shared.chunking import TARGET_MAX_TOKENS
from cani_shared.law.models import LawSection
from cani_shared.law.sectioner import chunk_sections


def _section(citation: str, text: str, order: int, heading: str | None = "Heading.") -> LawSection:
    return LawSection(
        citation=citation,
        heading=heading,
        text=text,
        source_url=f"https://example.test/{citation}",
        order=order,
    )


def test_one_section_one_chunk_when_within_budget():
    sections = [_section("NRS 116.001", "This chapter may be cited as the Act.", 0)]

    chunks = chunk_sections(sections)

    assert len(chunks) == 1
    assert chunks[0].citation == "NRS 116.001"
    assert chunks[0].text == sections[0].text
    assert chunks[0].part == 0
    assert chunks[0].chunk_index == 0


def test_chunk_index_is_sequential_across_sections():
    sections = [
        _section("NRS 116.001", "Short body one.", 0),
        _section("NRS 116.003", "Short body two.", 1),
        _section("NRS 116.005", "Short body three.", 2),
    ]

    chunks = chunk_sections(sections)

    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert [c.citation for c in chunks] == ["NRS 116.001", "NRS 116.003", "NRS 116.005"]


def test_oversized_section_splits_at_subsection_line_boundaries():
    # Each subsection line is well within budget individually, but together they exceed
    # TARGET_MAX_TOKENS, forcing a split. Lines must never be split mid-line.
    line = "This is a filler sentence that repeats several words to burn tokens steadily. " * 12
    lines = [f"{i}. {line.strip()}" for i in range(1, 10)]
    text = "\n".join(lines)
    sections = [_section("NRS 116.999", text, 0)]

    chunks = chunk_sections(sections)

    assert len(chunks) > 1
    # Every chunk belongs to the one section, in increasing part order, no gaps.
    assert all(c.citation == "NRS 116.999" for c in chunks)
    assert [c.part for c in chunks] == list(range(len(chunks)))
    # No line was split mid-way: each original line appears whole in exactly one chunk.
    all_chunk_lines = "\n".join(c.text for c in chunks).split("\n")
    assert all_chunk_lines == lines
    # No overlap: concatenating chunk text reproduces the original with no duplication.
    assert "\n".join(c.text for c in chunks) == text


def test_oversized_section_chunks_stay_within_budget():
    line = "This is a filler sentence that repeats several words to burn tokens steadily. " * 12
    lines = [f"{i}. {line.strip()}" for i in range(1, 10)]
    text = "\n".join(lines)
    sections = [_section("NRS 116.999", text, 0)]

    chunks = chunk_sections(sections)

    for c in chunks:
        assert c.token_count <= TARGET_MAX_TOKENS


def test_split_never_crosses_a_section_boundary():
    line = "This is a filler sentence that repeats several words to burn tokens steadily. " * 12
    big_text = "\n".join(f"{i}. {line.strip()}" for i in range(1, 10))
    sections = [
        _section("NRS 116.100", big_text, 0),
        _section("NRS 116.105", "A short unrelated section.", 1),
    ]

    chunks = chunk_sections(sections)

    citations_in_order = [c.citation for c in chunks]
    # All 116.100 parts come before 116.105 starts, and 116.105 never mixes with 116.100 text.
    last_100_index = max(i for i, c in enumerate(citations_in_order) if c == "NRS 116.100")
    first_105_index = next(i for i, c in enumerate(citations_in_order) if c == "NRS 116.105")
    assert last_100_index < first_105_index
    assert all(c.citation == "NRS 116.100" for c in chunks[: last_100_index + 1])
    assert all(c.citation == "NRS 116.105" for c in chunks[first_105_index:])


def test_no_overlap_between_split_parts():
    line = "This is a filler sentence that repeats several words to burn tokens steadily. " * 12
    text = "\n".join(f"{i}. {line.strip()}" for i in range(1, 10))
    sections = [_section("NRS 116.999", text, 0)]

    chunks = chunk_sections(sections)

    seen_lines: set[str] = set()
    for c in chunks:
        for chunk_line in c.text.split("\n"):
            assert chunk_line not in seen_lines, "line duplicated across chunk parts (overlap)"
            seen_lines.add(chunk_line)


def test_single_oversized_line_falls_back_to_sentence_split():
    # One subsection with no internal line breaks but many sentences — no natural line
    # boundary to split at, so the last-resort sentence-level split must still kick in.
    sentence = "This is one sentence that adds a modest number of tokens each time. "
    text = "1. " + sentence * 90
    sections = [_section("NRS 116.500", text, 0)]

    chunks = chunk_sections(sections)

    assert len(chunks) > 1
    assert all(c.citation == "NRS 116.500" for c in chunks)
    assert all(c.token_count <= TARGET_MAX_TOKENS for c in chunks)
