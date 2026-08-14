"""source_key -> zero-arg factory producing a LawSourceFetcher instance for that source.
Phase 1 (docs/20-public-law-corpus-design.md §20.11) ships exactly one entry — county code
(Washoe/Municode, sources/municode.py) is on hold per §20.12 Q1 and deliberately not built.
Adding a state or another NRS chapter later is a registry row (db/migrations) + one entry
here, not new pipeline code.
"""

from __future__ import annotations

from collections.abc import Callable

from cani_shared.law.fetcher import LawSourceFetcher
from cani_shared.law.sources.nrs import NrsChapterFetcher

SOURCE_REGISTRY: dict[str, Callable[[], LawSourceFetcher]] = {
    "nrs-116": lambda: NrsChapterFetcher(chapter="116"),
}
