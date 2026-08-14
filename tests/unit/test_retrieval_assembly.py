"""Unit coverage for retrieval_worker_app.assembly (docs/20-public-law-corpus-design.md
§20.8): dual-corpus budget enforcement, source-kind labeling, citation assembly, and
verdict suppression. Deliberately does NOT import retrieval_worker_app.main — that module
calls get_settings() at import time, which needs a full service environment; assembly.py
is pure by design so this logic is testable without one.
"""

from cani_shared.models import Citation, Verdict, VerdictKind
from cani_shared.vector.qdrant_client import ScoredChunk
from retrieval_worker_app.assembly import (
    LAW_CONTEXT_TOP_K,
    USER_CONTEXT_TOP_K,
    build_citations,
    build_context_chunks,
    law_source_label,
    legal_disclaimer,
    parse_jurisdictions,
    suppress_verdict_if_law_cited,
    top_k,
)


def _user_chunk(score: float, *, document_id: str = "doc-1", chunk_id: str | None = None) -> ScoredChunk:
    chunk_id = chunk_id or f"user-{score}"
    return ScoredChunk(
        point_id=chunk_id,
        score=score,
        payload={
            "document_id": document_id,
            "chunk_id": chunk_id,
            "chunk_text": f"user text {score}",
            "page_start": 1,
            "page_end": 1,
            "section_label": "7.2",
        },
    )


def _law_chunk(score: float, *, citation: str = "NRS 116.31065", jurisdiction: str = "us-nv") -> ScoredChunk:
    return ScoredChunk(
        point_id=f"law-{citation}",
        score=score,
        payload={
            "chunk_id": f"law-{citation}",
            "chunk_text": "Must be reasonably related to the purpose for which they are adopted.",
            "citation": citation,
            "jurisdiction": jurisdiction,
            "source_kind": "state_statute",
            "source_url": "https://www.leg.state.nv.us/NRS/NRS-116.html#NRS116Sec31065",
            "fetched_at": "2026-08-14T00:00:00+00:00",
        },
    )


# --- budget enforcement (§20.8: fixed per-corpus budgets, not merged ranking) ---


def test_user_budget_is_four():
    assert USER_CONTEXT_TOP_K == 4


def test_law_budget_is_three():
    assert LAW_CONTEXT_TOP_K == 3


def test_top_k_truncates_and_sorts_by_score_descending():
    candidates = [_user_chunk(0.1), _user_chunk(0.9), _user_chunk(0.5)]
    result = top_k(candidates, 2)
    assert [c.score for c in result] == [0.9, 0.5]


def test_top_k_never_exceeds_pool_size():
    candidates = [_user_chunk(s) for s in (0.9, 0.8, 0.7)]
    assert len(top_k(candidates, 10)) == 3


def test_law_budget_caps_even_with_more_candidates_available():
    candidates = [_law_chunk(s, citation=f"NRS 116.{s}") for s in (0.9, 0.8, 0.7, 0.6, 0.5)]
    result = top_k(candidates, LAW_CONTEXT_TOP_K)
    assert len(result) == 3
    assert [c.score for c in result] == [0.9, 0.8, 0.7]


# --- source-kind labeling ---


def test_build_context_chunks_labels_user_chunk_with_title_and_section():
    titles = {"doc-1": "Shadow Ridge CC&Rs"}
    chunks = build_context_chunks([_user_chunk(0.9)], [], titles)
    assert len(chunks) == 1
    assert chunks[0].source_kind == "user_document"
    assert chunks[0].source_label == 'your document "Shadow Ridge CC&Rs", 7.2'


def test_build_context_chunks_labels_law_chunk_with_citation_and_jurisdiction():
    chunks = build_context_chunks([], [_law_chunk(0.8)], {})
    assert len(chunks) == 1
    assert chunks[0].source_kind == "state_statute"
    assert chunks[0].source_label == "NRS 116.31065 (Nevada state law)"


def test_build_context_chunks_orders_user_before_law():
    chunks = build_context_chunks([_user_chunk(0.9)], [_law_chunk(0.8)], {"doc-1": "Doc"})
    assert chunks[0].source_kind == "user_document"
    assert chunks[1].source_kind == "state_statute"


def test_law_source_label_falls_back_to_jurisdiction_slug_when_unmapped():
    assert law_source_label({"citation": "WCC 10.050", "jurisdiction": "us-nv-washoe"}) == (
        "WCC 10.050 (us-nv-washoe)"
    )


def test_parse_jurisdictions_splits_and_trims():
    assert parse_jurisdictions("us-nv, us-nv-washoe ,,us") == ["us-nv", "us-nv-washoe", "us"]


# --- citation assembly ---


def test_build_citations_user_chunk_carries_page_range_and_no_law_fields():
    top_user = [_user_chunk(0.9, chunk_id="c1")]
    citations = build_citations([0], top_user, [], {"doc-1": "Shadow Ridge CC&Rs"})
    assert len(citations) == 1
    citation = citations[0]
    assert citation.source_kind == "user_document"
    assert citation.document_id == "doc-1"
    assert citation.page_start == 1
    assert citation.citation_ref is None


def test_build_citations_law_chunk_carries_citation_ref_and_no_page_range():
    top_law = [_law_chunk(0.8)]
    citations = build_citations([0], [], top_law, {})
    assert len(citations) == 1
    citation = citations[0]
    assert citation.source_kind == "state_statute"
    assert citation.document_id is None
    assert citation.page_start is None
    assert citation.citation_ref == "NRS 116.31065"
    assert citation.source_url
    assert citation.law_fetched_at is not None
    assert "reasonably related" in citation.snippet


def test_build_citations_indices_span_the_user_then_law_concatenation():
    top_user = [_user_chunk(0.9, chunk_id="c1")]
    top_law = [_law_chunk(0.8)]
    citations = build_citations([0, 1], top_user, top_law, {"doc-1": "Doc"})
    assert [c.source_kind for c in citations] == ["user_document", "state_statute"]


def test_build_citations_out_of_range_index_is_skipped():
    top_user = [_user_chunk(0.9, chunk_id="c1")]
    citations = build_citations([0, 5], top_user, [], {"doc-1": "Doc"})
    assert len(citations) == 1


# --- verdict suppression (Q4, §20.8/§20.12) ---


def _verdict() -> Verdict:
    return Verdict.from_kind(VerdictKind.YES_WITH_CONDITIONS)


def test_verdict_suppressed_when_any_citation_is_law_sourced():
    citations = [
        Citation(source_kind="user_document", document_id="doc-1", chunk_id="c1"),
        Citation(source_kind="state_statute", chunk_id="law-1", citation_ref="NRS 116.31065"),
    ]
    assert suppress_verdict_if_law_cited(_verdict(), citations) is None


def test_verdict_not_suppressed_for_document_only_citations():
    citations = [Citation(source_kind="user_document", document_id="doc-1", chunk_id="c1")]
    result = suppress_verdict_if_law_cited(_verdict(), citations)
    assert result is not None
    assert result.kind is VerdictKind.YES_WITH_CONDITIONS


def test_verdict_suppression_is_noop_when_verdict_already_none():
    citations = [Citation(source_kind="state_statute", chunk_id="law-1")]
    assert suppress_verdict_if_law_cited(None, citations) is None


def test_verdict_not_suppressed_for_law_only_citation_kind_check_is_inclusive():
    # Even a single non-user_document citation among several user_document ones suppresses.
    citations = [
        Citation(source_kind="user_document", document_id="doc-1", chunk_id="c1"),
        Citation(source_kind="user_document", document_id="doc-1", chunk_id="c2"),
        Citation(source_kind="county_code", chunk_id="c3"),
    ]
    assert suppress_verdict_if_law_cited(_verdict(), citations) is None


# --- disclaimer ---


def test_legal_disclaimer_extends_when_law_citation_present():
    citations = [Citation(source_kind="state_statute", chunk_id="law-1")]
    disclaimer = legal_disclaimer(citations)
    assert "not legal advice" in disclaimer
    assert "reproduced as fetched" in disclaimer


def test_legal_disclaimer_stays_short_for_document_only_citations():
    citations = [Citation(source_kind="user_document", document_id="doc-1", chunk_id="c1")]
    disclaimer = legal_disclaimer(citations)
    assert "not legal advice" in disclaimer
    assert "reproduced as fetched" not in disclaimer
