"""NRS chapter parser (docs/20 §20.5.2, §20.10) against a vendored, trimmed excerpt of the
real NRS 116 page (tests/fixtures/law/NRS-116-trimmed.html — public record). Assertions are
literal string equality on purpose: the verbatim-quote guarantee (§20.1 principle 1) is only
as good as this parser, so "close enough" text comparisons would defeat the point of the test.
"""

from __future__ import annotations

from pathlib import Path

from cani_shared.law.sources.nrs import parse_sections

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "law" / "NRS-116-trimmed.html"
_BASE_URL = "https://www.leg.state.nv.us/NRS/NRS-116.html"


def _sections():
    raw = _FIXTURE_PATH.read_bytes()
    return parse_sections(raw, base_url=_BASE_URL)


def test_section_count_and_order():
    sections = _sections()
    assert [s.citation for s in sections] == [
        "NRS 116.001",
        "NRS 116.003",
        "NRS 116.007",
        "NRS 116.31065",
    ]
    assert [s.order for s in sections] == [0, 1, 2, 3]


def test_short_section_byte_exact_text():
    sections = _sections()
    short_title = next(s for s in sections if s.citation == "NRS 116.001")
    assert short_title.heading == "Short title."
    assert short_title.text == "This chapter may be cited as the Uniform Common-Interest Ownership Act."


def test_anchor_urls_include_fragment():
    sections = _sections()
    short_title = next(s for s in sections if s.citation == "NRS 116.001")
    assert short_title.source_url == f"{_BASE_URL}#NRS116Sec001"

    rules = next(s for s in sections if s.citation == "NRS 116.31065")
    assert rules.source_url == f"{_BASE_URL}#NRS116Sec31065"


def test_multi_paragraph_section_preserves_subsection_lines():
    sections = _sections()
    affiliate = next(s for s in sections if s.citation == "NRS 116.007")
    assert affiliate.heading == "“Affiliate of a declarant” defined."
    lines = affiliate.text.split("\n")
    # Lead-in sentence, then "1. ...", "(a) ...", "(b) ...", "(c) ...", "(d) ...", "2. ...",
    # "(a) ...", "(b) ...", "(c) ...", "(d) ...", "3. ..." — 13 lines, none overlapping.
    assert len(lines) == 12
    assert lines[0].startswith("“Affiliate of a declarant” means")
    assert lines[1].startswith("1.")
    assert lines[2].startswith("(a)")
    assert lines[-1].startswith("3.")


def test_no_line_contains_raw_line_wrap_artifacts():
    # The source HTML hard-wraps lines mid-sentence for readability; the parser must
    # collapse that back to single spaces rather than leaking literal \r\n into quoted text.
    sections = _sections()
    for section in sections:
        assert "\r" not in section.text
        assert "  " not in section.text  # no doubled whitespace either


def test_duplicate_future_effective_citation_is_deduped_not_merged():
    # NRS-116-trimmed.html contains two bodies for 116.31065 back-to-back: the currently
    # effective version (anchored) and a future 'Effective July 1, 2026' amendment (not
    # anchored). Only the first is kept, and its text must not be merged with the second's.
    sections = _sections()
    matches = [s for s in sections if s.citation == "NRS 116.31065"]
    assert len(matches) == 1
    assert matches[0].heading == "Rules. [Effective through June 30, 2026.]"
    assert "Effective July 1, 2026" not in matches[0].text
    assert matches[0].text.count("Must be reasonably related") == 1
