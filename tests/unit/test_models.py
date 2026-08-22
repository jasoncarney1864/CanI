from datetime import UTC, datetime

from cani_shared.models import Citation, Document, DocumentListResponse, LegalTemplate


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


def _sample_document(**overrides) -> dict:
    base = dict(
        document_id="doc-1",
        owner_user_id="owner-1",
        title="hoa-rules.pdf",
        source_type="application/pdf",
        current_status="indexed",
        checksum="abc123",
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    base.update(overrides)
    return base


def test_document_origin_defaults_to_uploaded_for_pre_docs21_rows():
    # Old callers/rows predate the origin column (docs/21 §4) — must keep validating.
    document = Document(**_sample_document())
    assert document.origin == "uploaded"


def test_document_accepts_generated_origin():
    document = Document(**_sample_document(origin="generated"))
    assert document.origin == "generated"


def test_document_list_response_shape():
    envelope = DocumentListResponse(items=[Document(**_sample_document())], total=1, limit=50, offset=0)
    assert envelope.total == 1
    assert envelope.items[0].document_id == "doc-1"


def test_legal_template_validates_from_db_row_key_schema_json():
    # repositories.py hands model_validate() a psycopg dict_row keyed by the real column
    # name (schema_json) — field_schema's alias must match that exactly, or every
    # get_active_legal_template/list_active_legal_templates call breaks.
    row = dict(
        legal_template_id="tmpl-1",
        slug="nv-poa-financial",
        version=1,
        title="Nevada Durable Financial Power of Attorney",
        category="Legal",
        jurisdiction_note="Nevada only. Terminates at death — does not handle at-death transfer.",
        schema_json={"principal_name": {"type": "text", "label": "Principal's name", "required": True}},
        body_template="...",
        disclaimer_text="Not legal advice.",
        is_active=True,
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    template = LegalTemplate.model_validate(row)
    assert template.field_schema["principal_name"]["required"] is True

    # Also constructible by the Python attribute name (populate_by_name), for callers that
    # build a LegalTemplate directly rather than from a DB row.
    by_name_row = {k: v for k, v in row.items() if k != "schema_json"}
    template_by_name = LegalTemplate(**by_name_row, field_schema=row["schema_json"])
    assert template_by_name.field_schema == row["schema_json"]
