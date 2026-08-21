"""Compose the stored artifact for an AI-generated document (docs/21 §3.3 step 2).

The file is YAML front matter (provenance metadata) + a blank line + the answer's
markdown body — the same shape Jekyll/Hugo-style front matter uses, which is also exactly
what `cani_shared.providers.extractor`'s markdown branch knows how to strip before the
front matter is ever chunked/indexed. No YAML library dependency: nothing in this
pipeline ever parses the front matter back out (the extractor only strips it), so a small
hand-rolled emitter with correct string escaping is simpler than adding PyYAML as a new
dependency for a write-only format.
"""

from __future__ import annotations

from typing import Any

# docs/21 §3.3 — POST /documents/generated request-shape limits.
MAX_GENERATED_TITLE_LENGTH = 200
MAX_GENERATED_MARKDOWN_BYTES = 1024 * 1024  # 1 MiB
MAX_GENERATED_QUESTION_LENGTH = 2000
MAX_GENERATED_CITATIONS = 50
DERIVED_TITLE_QUESTION_CHARS = 80
DEFAULT_GENERATED_TITLE = "Generated document"


class GeneratedDocumentValidationError(Exception):
    """Raised with a human-readable message — docs-api maps this to a 400 whose `detail`
    the web proxy surfaces verbatim (matches docs_api_app.uploads.UploadValidationError's
    pattern for the upload path)."""


def validate_generated_document_request(
    *, title: str | None, spoke_is_valid: bool, spoke: str, markdown: str, question: str, citation_count: int
) -> None:
    """Pure size/shape validation for POST /documents/generated (docs/21 §3.3 step 1),
    kept independent of FastAPI/pydantic so it's testable without spinning up the app.
    `spoke_is_valid` is computed by the caller (docs-api owns the DocumentSpoke enum;
    this module intentionally has no cani_shared import) — this function only decides
    whether to raise, and with what message."""
    if title is not None and len(title) > MAX_GENERATED_TITLE_LENGTH:
        raise GeneratedDocumentValidationError(f"title exceeds {MAX_GENERATED_TITLE_LENGTH} characters")
    if not spoke_is_valid:
        raise GeneratedDocumentValidationError(f"Invalid spoke: {spoke}")
    markdown_bytes = len(markdown.encode("utf-8"))
    if not (1 <= markdown_bytes <= MAX_GENERATED_MARKDOWN_BYTES):
        raise GeneratedDocumentValidationError(
            f"markdown must be between 1 byte and {MAX_GENERATED_MARKDOWN_BYTES} bytes"
        )
    if len(question) > MAX_GENERATED_QUESTION_LENGTH:
        raise GeneratedDocumentValidationError(f"question exceeds {MAX_GENERATED_QUESTION_LENGTH} characters")
    if citation_count > MAX_GENERATED_CITATIONS:
        raise GeneratedDocumentValidationError(f"citations exceeds {MAX_GENERATED_CITATIONS} items")


def derive_title(*, title: str | None, question: str) -> str:
    """Title=title if given, else the question's first 80 chars, else a fixed fallback
    (docs/21 §3.3 step 4)."""
    return title or question.strip()[:DERIVED_TITLE_QUESTION_CHARS] or DEFAULT_GENERATED_TITLE


def _yaml_scalar(value: Any) -> str:
    """Render one YAML scalar: null, or a double-quoted string with backslashes and
    double-quotes escaped (YAML double-quoted scalars use C-style backslash escapes)."""
    if value is None:
        return "null"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def compose_generated_document(
    *,
    title: str,
    generated_at: str,
    question: str,
    model_id: str | None,
    citations: list[dict[str, str | None]],
) -> str:
    """Returns the front matter block only (caller appends the blank line + markdown body
    — kept separate so callers can compute a checksum over the exact bytes written)."""
    lines = [
        "---",
        f"title: {_yaml_scalar(title)}",
        f"generated_at: {_yaml_scalar(generated_at)}",
        f"question: {_yaml_scalar(question)}",
        f"model_id: {_yaml_scalar(model_id)}",
    ]
    if citations:
        lines.append("citations:")
        for citation in citations:
            lines.append(f"  - chunk_id: {_yaml_scalar(citation.get('chunk_id'))}")
            lines.append(f"    citation_ref: {_yaml_scalar(citation.get('citation_ref'))}")
    else:
        lines.append("citations: []")
    lines.append("---")
    return "\n".join(lines) + "\n"
