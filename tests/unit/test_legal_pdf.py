"""render_draft_html/render_body_text only — render_pdf_bytes needs weasyprint's native
GTK libraries, which this host doesn't have (see legal_pdf.py's module docstring); that
half is exercised by the integration suite against the real docs-api container instead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cani_shared.models import LegalTemplate
from docs_api_app.legal_pdf import render_body_text, render_draft_html


def _template(**overrides) -> LegalTemplate:
    base = dict(
        legal_template_id="tmpl-1",
        slug="nv-poa-financial",
        version=1,
        title="Nevada Durable Financial Power of Attorney",
        category="Legal",
        jurisdiction_note="Nevada only.",
        field_schema={"principal_name": {"type": "text", "label": "Principal's name", "required": True}},
        body_template="I, {principal_name}, appoint {agent_name} as my agent.",
        disclaimer_text="Drafted with CanI — not legal advice, not reviewed by an attorney.",
        is_active=True,
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    base.update(overrides)
    return LegalTemplate(**base)


def test_render_body_text_fills_known_fields():
    text = render_body_text(
        "I, {principal_name}, appoint {agent_name} as my agent.",
        {"principal_name": "Jane Doe", "agent_name": "John Doe"},
    )
    assert text == "I, Jane Doe, appoint John Doe as my agent."


def test_render_body_text_placeholders_missing_fields_instead_of_raising():
    # A preview of a partially-filled draft must render, not 500.
    text = render_body_text(
        "I, {principal_name}, appoint {agent_name} as my agent.", {"principal_name": "Jane Doe"}
    )
    assert text == "I, Jane Doe, appoint [not yet provided] as my agent."


def test_render_body_text_treats_empty_string_as_missing():
    text = render_body_text("Agent: {agent_name}.", {"agent_name": ""})
    assert text == "Agent: [not yet provided]."


def test_render_draft_html_includes_disclaimer_version_and_timestamp():
    html = render_draft_html(
        template=_template(),
        field_values={"principal_name": "Jane Doe", "agent_name": "John Doe"},
        generated_at="2026-08-21T12:00:00Z",
    )
    assert "Jane Doe" in html
    assert "John Doe" in html
    assert "not legal advice" in html
    assert "2026-08-21T12:00:00Z" in html
    assert "v1" in html


def test_render_draft_html_escapes_field_values():
    # Field values come from user chat / retrieval-worker citations, not a trusted author —
    # must not let one inject markup into the rendered document.
    html = render_draft_html(
        template=_template(),
        field_values={"principal_name": "<script>alert(1)</script>", "agent_name": "John Doe"},
        generated_at="2026-08-21T12:00:00Z",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
