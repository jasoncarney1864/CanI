"""Pure dual-corpus context/citation assembly for retrieve() (docs/20-public-law-corpus-design.md
§20.8). Split out from main.py so this logic is unit-testable without needing full service
settings (Postgres, Qdrant, secrets) at import time — main.py calls `get_settings()` at
module load, which requires a real environment; this module never does.
"""

from __future__ import annotations

from datetime import datetime

from cani_shared.models import Citation, Verdict
from cani_shared.providers.grounder import ContextChunk
from cani_shared.vector.qdrant_client import ScoredChunk

# Fixed per-corpus budgets, not merged ranking (§20.8): statutory boilerplate reliably
# out-scores messy scanned CC&Rs on generic legal phrasing, so a merged top-K pool would
# starve the user's own document. Keeping both present is the product goal ("your document
# says X; the statute says Y").
USER_CONTEXT_TOP_K = 4
LAW_CONTEXT_TOP_K = 3

# Human-readable jurisdiction labels for the source_label shown to the model/user. Falls
# back to the raw slug for any jurisdiction not yet in the map (multi-state is designed for
# even though v1 ships with one entry — docs/20 §20.8).
_JURISDICTION_LABELS = {"us-nv": "Nevada state law", "us": "federal law"}


def parse_jurisdictions(raw: str) -> list[str]:
    """settings.law_default_jurisdictions is a comma-separated slug list (§20.9)."""
    return [j.strip() for j in raw.split(",") if j.strip()]


def top_k(candidates: list[ScoredChunk], k: int) -> list[ScoredChunk]:
    return sorted(candidates, key=lambda c: c.score, reverse=True)[:k]


def law_source_label(payload: dict) -> str:
    jurisdiction = payload.get("jurisdiction", "")
    label = _JURISDICTION_LABELS.get(jurisdiction, jurisdiction or "public law")
    citation = payload.get("citation", "")
    return f"{citation} ({label})" if citation else label


def user_source_label(payload: dict, title: str) -> str:
    section = payload.get("section_label") or f"p.{payload.get('page_start')}"
    return f'your document "{title}", {section}'


def build_context_chunks(
    top_user: list[ScoredChunk], top_law: list[ScoredChunk], titles: dict[str, str]
) -> list[ContextChunk]:
    """Concatenated context list: user chunks first, then law chunks — [chunk:N] indices
    used elsewhere (grounder, citation assembly) span this same concatenation."""
    chunks = [
        ContextChunk(
            text=c.payload.get("chunk_text", ""),
            source_label=user_source_label(
                c.payload, titles.get(c.payload.get("document_id", ""), "Untitled document")
            ),
            source_kind="user_document",
        )
        for c in top_user
    ]
    chunks.extend(
        ContextChunk(
            text=c.payload.get("chunk_text", ""),
            source_label=law_source_label(c.payload),
            source_kind=c.payload.get("source_kind", "state_statute"),
        )
        for c in top_law
    )
    return chunks


def build_citations(
    used_chunk_indices: list[int],
    top_user: list[ScoredChunk],
    top_law: list[ScoredChunk],
    titles: dict[str, str],
) -> list[Citation]:
    """Indices are into the same user+law concatenation build_context_chunks produced."""
    combined = top_user + top_law
    citations: list[Citation] = []
    for idx in used_chunk_indices:
        if idx >= len(combined):
            continue
        chunk = combined[idx]
        if idx < len(top_user):
            document_id = chunk.payload["document_id"]
            citations.append(
                Citation(
                    source_kind="user_document",
                    document_id=document_id,
                    document_title=titles.get(document_id, "Untitled document"),
                    page_start=chunk.payload["page_start"],
                    page_end=chunk.payload["page_end"],
                    section_label=chunk.payload.get("section_label"),
                    chunk_id=chunk.payload["chunk_id"],
                    # Same owner-filtered chunk the grounder cited — safe to surface
                    # verbatim so the client can render and spotlight the source passage.
                    snippet=chunk.payload.get("chunk_text"),
                )
            )
        else:
            fetched_at_raw = chunk.payload.get("fetched_at")
            citations.append(
                Citation(
                    source_kind=chunk.payload.get("source_kind", "state_statute"),
                    chunk_id=chunk.payload["chunk_id"],
                    # This snippet IS the verbatim quoted statute text (§20.1 principle 1).
                    snippet=chunk.payload.get("chunk_text"),
                    citation_ref=chunk.payload.get("citation"),
                    source_url=chunk.payload.get("source_url"),
                    law_fetched_at=datetime.fromisoformat(fetched_at_raw) if fetched_at_raw else None,
                )
            )
    return citations


def suppress_verdict_if_law_cited(verdict: Verdict | None, citations: list[Citation]) -> Verdict | None:
    """Q4 (docs/20 §20.8, §20.12): the yes/no badge reads as exactly the legal *opinion*
    product principle 1 forbids once statute text is in play. Suppression is scoped
    narrowly — only the badge disappears; citations, quotes, and the plain-language answer
    render untouched. Document-only answers (the common case today) are unaffected."""
    if verdict is None:
        return None
    if any(c.source_kind != "user_document" for c in citations):
        return None
    return verdict


def legal_disclaimer(citations: list[Citation]) -> str:
    """Q3 (decided): a quiet per-citation "as of {date}" story is carried by the citations
    themselves (law_fetched_at) — this prefix just adds one sentence of context, no
    escalating warning banner, when any law citation is present."""
    base = (
        "⚖️ Legal Disclaimer: This is not legal advice. Consult a qualified attorney for "
        "your specific situation."
    )
    if any(c.source_kind != "user_document" for c in citations):
        base += " Statute text is reproduced as fetched on the cited date and may have been amended since."
    return base
