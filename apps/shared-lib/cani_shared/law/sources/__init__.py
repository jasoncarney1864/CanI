"""source_key -> zero-arg factory producing a LawSourceFetcher instance for that source.
County code (Washoe/Municode, sources/municode.py) is on hold per docs/20 §20.12 Q1 and
deliberately not built. Adding a state or another NRS chapter is a registry row
(db/migrations) + one entry here, not new pipeline code — nrs-162a (Sprint 4, the POA
drafting template's statutory basis) is the proof: no pipeline changes, just this line and
a law_sources seed row.
"""

from __future__ import annotations

from collections.abc import Callable

from cani_shared.law.fetcher import LawSourceFetcher
from cani_shared.law.sources.nrs import NrsChapterFetcher

SOURCE_REGISTRY: dict[str, Callable[[], LawSourceFetcher]] = {
    "nrs-116": lambda: NrsChapterFetcher(chapter="116"),
    "nrs-162a": lambda: NrsChapterFetcher(chapter="162A"),
}
