"""Text extraction per docs/08-rag-pipeline-design.md §8.4: attempt native text
extraction first for digitally generated PDFs, fall back to OCR via Azure AI Document
Intelligence for scanned PDFs/images. Preserve page boundaries for citations.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from pypdf import PdfReader

from cani_shared.chunking import PageText

EXTRACTOR_VERSION = "v1-native-pdf+azure-di"

_MARKDOWN_CONTENT_TYPES = ("text/markdown", "text/plain")

# YAML front matter block: a leading "---" line, content, then a closing "---" line.
# docs/21 §3.3 composes generated documents as front matter + blank line + markdown; the
# front matter is provenance metadata (question, model_id, citations) that must not be
# embedded/chunked/searched as if it were the document's actual content.
_FRONT_MATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)


def _strip_front_matter(text: str) -> str:
    return _FRONT_MATTER_RE.sub("", text, count=1)


# Below this average chars/page, treat native extraction as unreliable (likely a scan)
# and fall back to OCR. Simple heuristic, tunable — flagged as an open question in §8.15.
MIN_CHARS_PER_PAGE_FOR_NATIVE = 20


@dataclass
class ExtractionResult:
    pages: list[PageText]
    method: str  # "native" | "ocr"


class OcrUnavailableError(RuntimeError):
    """A document needs OCR (scanned PDF or image) but Azure Document Intelligence is not
    configured. This is a permanent condition for the document — no amount of retrying
    makes an unconfigured credential appear — so the ingestion pipeline maps it to a
    permanent job failure rather than burning retries on it (docs/08 §8.10)."""


class TextExtractor(ABC):
    @abstractmethod
    def extract(self, file_bytes: bytes, content_type: str) -> ExtractionResult: ...


class NativeThenOcrExtractor(TextExtractor):
    """Real implementation: pypdf native extraction, Azure Document Intelligence OCR fallback.

    OCR requires `di_endpoint` + `di_api_key`. When they are absent (e.g. a dev cluster
    that never had the Document Intelligence secret delivered), native PDF extraction still
    works, but a document that actually needs OCR raises OcrUnavailableError with a clear
    message — instead of the previous behaviour, where an empty endpoint produced a cryptic
    "No connection adapters were found" and got retried as if it were transient.
    """

    def __init__(self, *, di_endpoint: str, di_api_key: str):
        self._di_endpoint = di_endpoint
        self._di_api_key = di_api_key
        self._ocr_available = bool(di_endpoint and di_api_key)

    def extract(self, file_bytes: bytes, content_type: str) -> ExtractionResult:
        if content_type in _MARKDOWN_CONTENT_TYPES:
            # Generated documents (docs/21 §3.1) and any future plain-text upload path —
            # no OCR fallback needed, the "extraction" is just a decode.
            text = _strip_front_matter(file_bytes.decode("utf-8", errors="replace"))
            return ExtractionResult(pages=[PageText(page_number=1, text=text)], method="native-text")
        if content_type == "application/pdf":
            native = self._try_native_pdf(file_bytes)
            if native is not None:
                return ExtractionResult(pages=native, method="native")
        # Reaching here means OCR is required: a scanned/no-text PDF, or a non-PDF (image).
        if not self._ocr_available:
            raise OcrUnavailableError(
                f"document requires OCR (content_type={content_type}) but Azure Document "
                "Intelligence is not configured "
                "(AZURE_DOCUMENTINTELLIGENCE_ENDPOINT / AZURE_DOCUMENTINTELLIGENCE_API_KEY)"
            )
        return ExtractionResult(pages=self._ocr(file_bytes, content_type), method="ocr")

    def _try_native_pdf(self, file_bytes: bytes) -> list[PageText] | None:
        import io

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageText(page_number=i, text=text))
        avg_chars = sum(len(p.text) for p in pages) / max(len(pages), 1)
        if avg_chars < MIN_CHARS_PER_PAGE_FOR_NATIVE:
            return None
        return pages

    def _ocr(self, file_bytes: bytes, content_type: str) -> list[PageText]:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
        from azure.core.credentials import AzureKeyCredential

        client = DocumentIntelligenceClient(
            endpoint=self._di_endpoint,
            credential=AzureKeyCredential(self._di_api_key),
            # Bound both the initial call and any retries — an unresponsive DI endpoint
            # must fail loudly, not hang the worker forever (connection/read timeouts in
            # seconds, per azure-core transport options).
            connection_timeout=10,
            read_timeout=60,
        )
        poller = client.begin_analyze_document(
            "prebuilt-read", AnalyzeDocumentRequest(bytes_source=file_bytes)
        )
        # Bound the polling wait too, for the same reason.
        result = poller.result(timeout=120)
        pages = []
        for page in result.pages or []:
            text = "\n".join(line.content for line in (page.lines or []))
            pages.append(PageText(page_number=page.page_number, text=text))
        return pages


class FakeExtractor(TextExtractor):
    """Deterministic extractor for unit tests — no network calls."""

    def __init__(self, canned_pages: list[PageText] | None = None):
        self._canned_pages = canned_pages

    def extract(self, file_bytes: bytes, content_type: str) -> ExtractionResult:
        if self._canned_pages is not None:
            return ExtractionResult(pages=self._canned_pages, method="native")
        text = file_bytes.decode("utf-8", errors="ignore")
        return ExtractionResult(pages=[PageText(page_number=1, text=text)], method="native")
