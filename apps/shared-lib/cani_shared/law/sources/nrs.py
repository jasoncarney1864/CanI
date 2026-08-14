"""Fetcher + parser for a Nevada Revised Statutes chapter published as a single static HTML
page (docs/20-public-law-corpus-design.md §20.5.2). NRS 116 is the only chapter wired up in
v1 (§20.11); other chapters are a registry row + NrsChapterFetcher(chapter=...) away.

Politeness (§20.5.1): a descriptive User-Agent with a contact address, a bounded timeout, and
no concurrency — this fetches one chapter page per call, so there's nothing to rate-limit
within a single fetch. Multi-page sources would need the ~1req/sec delay this doesn't have.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from cani_shared.law.fetcher import LawSourceFetcher
from cani_shared.law.models import FetchedLawDocument, LawSection

_BASE_URL = "https://www.leg.state.nv.us/NRS/NRS-{chapter}.html"
_USER_AGENT = "CanIDocsBot/1.0 (+https://app.canido.co; contact: ops@canido.co)"
_TIMEOUT_SECONDS = 30.0

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Collapse whitespace (including entity-decoded figure/en-spaces used as visual
    alignment in the source markup, and the hard line-wraps the page uses mid-sentence for
    readability) to single regular spaces, then trim. This is the 'trim whitespace, decode
    entities, nothing else' rule from the fetcher contract — bs4 already decodes entities via
    get_text(); this is the 'trim whitespace' half."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _text_after(parent, marker) -> str:
    """Text of parent's child nodes that appear after the `marker` child tag — used to pull
    the lead-in sentence that follows a section's heading span within the same <p>."""
    parts: list[str] = []
    started = False
    for node in parent.contents:
        if node is marker:
            started = True
            continue
        if started:
            parts.append(node.get_text() if hasattr(node, "get_text") else str(node))
    return "".join(parts)


def parse_sections(raw_bytes: bytes, *, base_url: str) -> list[LawSection]:
    """Parse a NRS chapter page into section-aligned LawSections.

    Each section starts at a `<p class="SectBody">` containing a `<span class="Section">`
    (the citation number) and a `<span class="Leadline">` (the heading); subsequent
    `<p class="SectBody">` paragraphs without a Section span are that section's body
    continuing, one paragraph per line, until the next Section-bearing paragraph.
    `<p class="SourceNote">` paragraphs are bibliographic amendment history, not statute
    text, and are skipped.

    NRS occasionally publishes two bodies back-to-back for one citation — the currently
    effective text and a future-dated amendment (e.g. heading 'Rules. [Effective July 1,
    2026.]') — where only the first (currently effective) occurrence carries the `<a name=...>`
    anchor. Only the first occurrence of each citation is kept; later duplicates are dropped
    rather than merged into the first section's text, which would silently splice two
    different versions of the law together under one citation.
    """
    soup = BeautifulSoup(raw_bytes, "html.parser", from_encoding="windows-1252")

    blocks: list[dict] = []
    current: dict | None = None
    for p in soup.find_all("p", class_=("SectBody", "SourceNote")):
        classes = p.get("class") or []
        if "SourceNote" in classes:
            continue
        section_span = p.find("span", class_="Section")
        if section_span is not None:
            citation = f"NRS {_normalize(section_span.get_text())}"
            anchor = p.find("a", attrs={"name": True})
            leadline = p.find("span", class_="Leadline")
            heading = _normalize(leadline.get_text()) if leadline else None
            lead_text = _normalize(_text_after(p, leadline)) if leadline else _normalize(p.get_text())
            current = {
                "citation": citation,
                "heading": heading,
                "anchor_name": anchor["name"] if anchor else None,
                "paragraphs": [lead_text] if lead_text else [],
            }
            blocks.append(current)
        elif current is not None:
            current["paragraphs"].append(_normalize(p.get_text()))

    sections: list[LawSection] = []
    seen_citations: set[str] = set()
    order = 0
    for block in blocks:
        if block["citation"] in seen_citations:
            continue
        seen_citations.add(block["citation"])

        anchor_name = block["anchor_name"]
        if anchor_name is None:
            # Defensive fallback only — every real NRS section observed carries an anchor on
            # its first (currently effective) occurrence. Derives the same
            # 'NRS<chapter>Sec<suffix>' shape the site itself uses rather than raising and
            # failing the whole chapter fetch over one malformed section.
            anchor_name = "NRS" + block["citation"].split(" ", 1)[1].replace(".", "Sec", 1)

        text = "\n".join(t for t in block["paragraphs"] if t)
        sections.append(
            LawSection(
                citation=block["citation"],
                heading=block["heading"],
                text=text,
                source_url=f"{base_url}#{anchor_name}",
                order=order,
            )
        )
        order += 1
    return sections


class NrsChapterFetcher(LawSourceFetcher):
    def __init__(self, chapter: str = "116"):
        self.chapter = chapter
        self.source_key = f"nrs-{chapter}"

    def fetch(self) -> FetchedLawDocument:
        url = _BASE_URL.format(chapter=self.chapter)
        response = httpx.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS, follow_redirects=True
        )
        response.raise_for_status()
        raw_bytes = response.content
        sections = parse_sections(raw_bytes, base_url=url)
        return FetchedLawDocument(raw_bytes=raw_bytes, content_type="text/html", sections=sections)
