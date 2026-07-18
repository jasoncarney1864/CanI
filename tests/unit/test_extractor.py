"""Extraction fallback behaviour, focused on the OCR-unavailable path (docs/08 §8.4).

The regression these guard against: when Document Intelligence is unconfigured, a document
that needs OCR must fail *clearly and permanently* — not with a cryptic empty-endpoint
network error that the pipeline retries five times before dead-lettering.
"""

from __future__ import annotations

import io

import pytest
from cani_shared.providers.extractor import (
    MIN_CHARS_PER_PAGE_FOR_NATIVE,
    NativeThenOcrExtractor,
    OcrUnavailableError,
)
from pypdf import PdfWriter


def _blank_pdf() -> bytes:
    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buf)
    return buf.getvalue()


def _digital_pdf_with_text() -> bytes:
    # reportlab draws a real text layer, so pypdf native extraction succeeds without OCR.
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "This is a digitally generated PDF with an extractable text layer. " * 5)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_ocr_needed_but_unconfigured_raises_clear_error():
    """A no-text PDF forces the OCR path; with DI unconfigured that must be a clear,
    permanent OcrUnavailableError, not a network error."""
    extractor = NativeThenOcrExtractor(di_endpoint="", di_api_key="")
    with pytest.raises(OcrUnavailableError) as exc:
        extractor.extract(_blank_pdf(), "application/pdf")
    # Message names the missing config so the operator knows exactly what to fix.
    assert "AZURE_DOCUMENTINTELLIGENCE_ENDPOINT" in str(exc.value)


def test_non_pdf_without_ocr_raises_clear_error():
    """Images have no native path at all, so they always need OCR."""
    extractor = NativeThenOcrExtractor(di_endpoint="", di_api_key="")
    with pytest.raises(OcrUnavailableError):
        extractor.extract(b"\x89PNG fake image bytes", "image/png")


def test_digital_pdf_extracts_natively_without_ocr():
    """The happy path still works with DI unconfigured — native extraction needs no OCR."""
    extractor = NativeThenOcrExtractor(di_endpoint="", di_api_key="")
    result = extractor.extract(_digital_pdf_with_text(), "application/pdf")
    assert result.method == "native"
    assert result.pages
    avg_chars = sum(len(p.text) for p in result.pages) / len(result.pages)
    assert avg_chars >= MIN_CHARS_PER_PAGE_FOR_NATIVE
