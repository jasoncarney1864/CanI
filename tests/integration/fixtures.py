"""Test-only helper to generate a small real PDF with extractable text, so integration
tests exercise the actual native-PDF-extraction path (§8.4) rather than a fake payload.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def make_sample_pdf(paragraphs: list[str]) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    y = 720
    for paragraph in paragraphs:
        c.drawString(72, y, paragraph)
        y -= 40
        if y < 72:
            c.showPage()
            y = 720
    c.save()
    return buffer.getvalue()
