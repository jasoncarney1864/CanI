"""Fetcher contract for public-law sources (docs/20-public-law-corpus-design.md §20.5.1).
Fetch and parse are one step on purpose: each source's parser is coupled to that source's
markup, and keeping them together means a markup change breaks loudly inside the one module
that owns that source. Parsers must be lossless on section text — trim whitespace, decode
entities, nothing else. The verbatim-quote guarantee (§20.1 principle 1) is only as good as
this code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from cani_shared.law.models import FetchedLawDocument, LawSection

_FAKE_BASE_URL = "https://www.leg.state.nv.us/NRS/NRS-116.html"


class LawSourceFetcher(ABC):
    source_key: str

    @abstractmethod
    def fetch(self) -> FetchedLawDocument: ...


class FakeLawFetcher(LawSourceFetcher):
    """Deterministic fetcher for CI/tests and any environment with CANI_LAW_FETCH_ENABLED
    unset — no network calls, ever. Same philosophy as FakeEmbedder/FakeGrounder: fake
    infrastructure, real-shaped content. Serves a small, genuine excerpt of NRS 116 (public
    record) so tests exercise real statute text rather than placeholder strings.

    Ignores which real source `source_key` names — the fake corpus is the same small NRS 116
    excerpt regardless, which is fine because build_law_fetchers() only ever constructs one
    of these per registered source_key and callers key results by that source_key anyway.
    """

    def __init__(self, source_key: str):
        self.source_key = source_key

    def fetch(self) -> FetchedLawDocument:
        sections = [
            LawSection(
                citation="NRS 116.001",
                heading="Short title.",
                text="This chapter may be cited as the Uniform Common-Interest Ownership Act.",
                source_url=f"{_FAKE_BASE_URL}#NRS116Sec001",
                order=0,
            ),
            LawSection(
                citation="NRS 116.31065",
                heading="Rules.",
                text=(
                    "The rules adopted by an association:\n"
                    "1. Must be reasonably related to the purpose for which they are adopted.\n"
                    "2. Must be sufficiently explicit in their prohibition, direction or "
                    "limitation to inform a person of any action or omission required for "
                    "compliance.\n"
                    "3. Must not be adopted to evade any obligation of the association."
                ),
                source_url=f"{_FAKE_BASE_URL}#NRS116Sec31065",
                order=1,
            ),
        ]
        raw_bytes = "\n\n".join(f"{s.citation} {s.heading}\n{s.text}" for s in sections).encode("utf-8")
        return FetchedLawDocument(raw_bytes=raw_bytes, content_type="text/plain", sections=sections)
