from datetime import UTC, datetime

from cani_shared.models import Citation


def test_citation_legacy_payload_still_validates():
    # Old callers/tests construct Citation without source_kind or any law field at all —
    # this must keep validating exactly as it did before docs/20 §20.8 extended the model.
    citation = Citation(
        document_id="doc-1",
        document_title="Shadow Ridge CC&Rs",
        page_start=3,
        page_end=3,
        section_label="7.2",
        chunk_id="chunk-1",
        snippet="No pets over 40 lbs.",
    )
    assert citation.source_kind == "user_document"
    assert citation.citation_ref is None
    assert citation.source_url is None
    assert citation.law_fetched_at is None


def test_citation_accepts_law_fields_without_page_range():
    citation = Citation(
        source_kind="state_statute",
        chunk_id="law-chunk-1",
        snippet="Must be reasonably related to the purpose for which they are adopted.",
        citation_ref="NRS 116.31065",
        source_url="https://www.leg.state.nv.us/NRS/NRS-116.html#NRS116Sec31065",
        law_fetched_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    assert citation.document_id is None
    assert citation.page_start is None
    assert citation.page_end is None
    assert citation.citation_ref == "NRS 116.31065"


def test_citation_serializes_law_citation_round_trip():
    citation = Citation(
        source_kind="state_statute",
        chunk_id="law-chunk-1",
        citation_ref="NRS 116.001",
        source_url="https://example.invalid/NRS-116.html#NRS116Sec001",
    )
    payload = citation.model_dump()
    restored = Citation.model_validate(payload)
    assert restored == citation
