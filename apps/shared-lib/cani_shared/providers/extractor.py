"""Text extraction per docs/08-rag-pipeline-design.md §8.4: attempt native text
extraction first for digitally generated PDFs, fall back to OCR via Azure AI Document
Intelligence for scanned PDFs/images. Preserve page boundaries for citations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pypdf import PdfReader

from cani_shared.chunking import PageText

EXTRACTOR_VERSION = "v1-native-pdf+azure-di"

# Below this average chars/page, treat native extraction as unreliable (likely a scan)
# and fall back to OCR. Simple heuristic, tunable — flagged as an open question in §8.15.
MIN_CHARS_PER_PAGE_FOR_NATIVE = 20


@dataclass
class ExtractionResult:
    pages: list[PageText]
    method: str  # "native" | "ocr"


class TextExtractor(ABC):
    @abstractmethod
    def extract(self, file_bytes: bytes, content_type: str) -> ExtractionResult: ...


class NativeThenOcrExtractor(TextExtractor):
    """Real implementation: pypdf native extraction, Azure Document Intelligence OCR fallback."""

    def __init__(self, *, di_endpoint: str, di_api_key: str):
        self._di_endpoint = di_endpoint
        self._di_api_key = di_api_key

    def extract(self, file_bytes: bytes, content_type: str) -> ExtractionResult:
        if content_type == "application/pdf":
            native = self._try_native_pdf(file_bytes)
            if native is not None:
                return ExtractionResult(pages=native, method="native")
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
            endpoint=self._di_endpoint, credential=AzureKeyCredential(self._di_api_key)
        )
        poller = client.begin_analyze_document(
            "prebuilt-read", AnalyzeDocumentRequest(bytes_source=file_bytes)
        )
        result = poller.result()
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
