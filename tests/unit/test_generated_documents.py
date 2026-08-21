"""POST /documents/generated's pure helpers (docs/21 §3.3): request-size validation,
title derivation, and front-matter composition — none of it touches FastAPI/DB, so it's
tested directly rather than through the route."""

from __future__ import annotations

import pytest
from docs_api_app.generated_documents import (
    MAX_GENERATED_CITATIONS,
    MAX_GENERATED_MARKDOWN_BYTES,
    MAX_GENERATED_QUESTION_LENGTH,
    MAX_GENERATED_TITLE_LENGTH,
    GeneratedDocumentValidationError,
    compose_generated_document,
    derive_title,
    validate_generated_document_request,
)


def _valid_kwargs(**overrides):
    kwargs = dict(
        title=None,
        spoke_is_valid=True,
        spoke="General",
        markdown="Some answer text.",
        question="Can I sublet?",
        citation_count=1,
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_request_raises_nothing():
    validate_generated_document_request(**_valid_kwargs())  # no raise


def test_title_over_limit_rejected():
    with pytest.raises(GeneratedDocumentValidationError, match="title"):
        validate_generated_document_request(**_valid_kwargs(title="x" * (MAX_GENERATED_TITLE_LENGTH + 1)))


def test_title_at_limit_accepted():
    validate_generated_document_request(**_valid_kwargs(title="x" * MAX_GENERATED_TITLE_LENGTH))


def test_invalid_spoke_rejected():
    with pytest.raises(GeneratedDocumentValidationError, match="Invalid spoke"):
        validate_generated_document_request(**_valid_kwargs(spoke_is_valid=False, spoke="Bogus"))


def test_empty_markdown_rejected():
    with pytest.raises(GeneratedDocumentValidationError, match="markdown"):
        validate_generated_document_request(**_valid_kwargs(markdown=""))


def test_markdown_over_1mib_rejected():
    with pytest.raises(GeneratedDocumentValidationError, match="markdown"):
        validate_generated_document_request(
            **_valid_kwargs(markdown="x" * (MAX_GENERATED_MARKDOWN_BYTES + 1))
        )


def test_markdown_at_1mib_accepted():
    validate_generated_document_request(**_valid_kwargs(markdown="x" * MAX_GENERATED_MARKDOWN_BYTES))


def test_question_over_limit_rejected():
    with pytest.raises(GeneratedDocumentValidationError, match="question"):
        validate_generated_document_request(
            **_valid_kwargs(question="x" * (MAX_GENERATED_QUESTION_LENGTH + 1))
        )


def test_too_many_citations_rejected():
    with pytest.raises(GeneratedDocumentValidationError, match="citations"):
        validate_generated_document_request(**_valid_kwargs(citation_count=MAX_GENERATED_CITATIONS + 1))


def test_max_citations_accepted():
    validate_generated_document_request(**_valid_kwargs(citation_count=MAX_GENERATED_CITATIONS))


# --- derive_title ------------------------------------------------------------------


def test_derive_title_uses_given_title():
    assert derive_title(title="My Title", question="irrelevant") == "My Title"


def test_derive_title_falls_back_to_question_prefix():
    long_question = "x" * 200
    assert derive_title(title=None, question=long_question) == "x" * 80


def test_derive_title_falls_back_to_default_when_question_is_blank():
    assert derive_title(title=None, question="   ") == "Generated document"


# --- compose_generated_document -----------------------------------------------------


def test_compose_includes_all_fields_and_escapes_quotes():
    front_matter = compose_generated_document(
        title='A "quoted" title',
        generated_at="2026-08-20T00:00:00Z",
        question="Can I sublet?",
        model_id="claude-sonnet-5",
        citations=[{"chunk_id": "chunk-1", "citation_ref": "NRS 116.31065"}],
    )
    assert front_matter.startswith("---\n")
    assert front_matter.rstrip("\n").endswith("---")
    assert 'title: "A \\"quoted\\" title"' in front_matter
    assert 'generated_at: "2026-08-20T00:00:00Z"' in front_matter
    assert 'chunk_id: "chunk-1"' in front_matter
    assert 'citation_ref: "NRS 116.31065"' in front_matter


def test_compose_with_no_citations_emits_empty_list():
    front_matter = compose_generated_document(
        title="Title", generated_at="2026-08-20T00:00:00Z", question="Q", model_id=None, citations=[]
    )
    assert "citations: []" in front_matter
    assert "model_id: null" in front_matter
