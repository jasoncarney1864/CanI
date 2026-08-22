"""Renders a finalized legal draft to PDF (Sprint 4 Task 5).

Split into a pure HTML-composition step and a WeasyPrint rendering step on purpose:
WeasyPrint needs native GTK libraries (pango/cairo/gdk-pixbuf) that are present in the
docs-api container image but not on every machine that runs `pytest tests/unit` (this
repo's Windows dev host included — WeasyPrint fails to import there with an OSError from
cffi.dlopen, the same class of host-vs-container gap CLAUDE.md documents for
grpcio/cryptography on ARM64). Importing weasyprint lazily, only inside render_pdf_bytes,
means importing this module — and unit-testing render_draft_html — never requires those
libraries. render_pdf_bytes itself is exercised by the integration suite against the real
docker-compose docs-api container, which has them.
"""

from __future__ import annotations

import html
from string import Formatter
from typing import Any

from cani_shared.models import LegalTemplate

_PLACEHOLDER = "[not yet provided]"


class _MissingFieldFormatter(Formatter):
    """format_map, but a missing/empty field renders as a visible placeholder instead of
    raising KeyError — a preview must render for a partially-filled draft, and a finalize
    of an incomplete draft should be visibly wrong on the page rather than a 500."""

    def get_value(self, key: object, args: Any, kwargs: dict) -> Any:
        value = kwargs.get(key) if isinstance(key, str) else None
        if value is None or value == "":
            return _PLACEHOLDER
        return value


def render_body_text(body_template: str, field_values: dict[str, Any]) -> str:
    """Fills `{field_key}` placeholders in a template's body_template. Pure string
    substitution — no field-type awareness, since schema_json's `type` is about how the
    conversational UI collects a value, not how it's printed."""
    return _MissingFieldFormatter().vformat(body_template, (), field_values)


def render_draft_html(
    *,
    template: LegalTemplate,
    field_values: dict[str, Any],
    generated_at: str,
) -> str:
    """Full standalone HTML document for WeasyPrint: the rendered body plus a disclaimer
    banner up top and a running footer (disclaimer + generation timestamp + template
    version) on every page via CSS @page — Task 5's "every generated PDF must have a
    footer/header disclaimer, generation timestamp, and template version baked in"."""
    body_text = render_body_text(template.body_template, field_values)
    footer_text = (
        f"{template.disclaimer_text} — Generated {generated_at} — {template.title} v{template.version}"
    )
    body_html = "".join(f"<p>{html.escape(line)}</p>" for line in body_text.split("\n") if line.strip())

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(template.title)}</title>
<style>
  @page {{
    size: letter;
    margin: 1in 1in 1.25in 1in;
    @bottom-center {{
      content: "{html.escape(footer_text)}";
      font-size: 8pt;
      color: #555;
    }}
  }}
  body {{ font-family: "DejaVu Serif", serif; font-size: 11pt; line-height: 1.5; color: #111; }}
  .disclaimer {{
    border: 1px solid #b45309;
    background: #fffbeb;
    padding: 0.5em 0.75em;
    font-size: 9pt;
    margin-bottom: 1.5em;
  }}
  h1 {{ font-size: 14pt; text-align: center; }}
  p {{ margin: 0 0 0.75em 0; }}
</style>
</head>
<body>
  <div class="disclaimer">{html.escape(template.disclaimer_text)}</div>
  <h1>{html.escape(template.title)}</h1>
  {body_html}
</body>
</html>
"""


def render_pdf_bytes(html_content: str) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415 - see module docstring

    return HTML(string=html_content).write_pdf()
