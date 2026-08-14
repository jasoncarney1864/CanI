"""Fetcher-facing dataclasses for the public-law corpus (docs/20-public-law-corpus-design.md
§20.5.1). Distinct from cani_shared.models: these describe what a fetcher hands back before
anything is persisted, not the DB/Qdrant-facing shapes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LawSection:
    citation: str  # 'NRS 116.31065'
    heading: str | None  # 'Rules.'
    text: str  # verbatim section body — never normalized beyond whitespace
    source_url: str  # deep link incl. anchor
    order: int  # document order within the source


@dataclass
class FetchedLawDocument:
    raw_bytes: bytes  # exactly what the wire returned — snapshotted to blob as-is
    content_type: str
    sections: list[LawSection]
