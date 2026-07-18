"""Single place that decides real-vs-fake providers from config, so ingestion-worker and
retrieval-worker always agree on which embedding space is in use. CI and any environment
without Azure AI keys configured automatically fall back to the deterministic fakes —
tests never require live credentials, but local dev with a real .env exercises the real
Azure OpenAI / Document Intelligence path end-to-end.
"""

from __future__ import annotations

from cani_shared.config import Settings
from cani_shared.providers.embedder import AzureOpenAIEmbedder, Embedder, FakeEmbedder
from cani_shared.providers.extractor import NativeThenOcrExtractor, TextExtractor
from cani_shared.providers.grounder import AzureOpenAIChatGrounder, ChatGrounder, FakeGrounder


def build_embedder(settings: Settings) -> Embedder:
    if settings.azure_ai_providers_configured and settings.azure_openai_embedding_deployment:
        return AzureOpenAIEmbedder(
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            deployment=settings.azure_openai_embedding_deployment,
        )
    return FakeEmbedder()


def build_chat_grounder(settings: Settings) -> ChatGrounder:
    if settings.azure_ai_providers_configured and settings.azure_openai_chat_deployment:
        return AzureOpenAIChatGrounder(
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            deployment=settings.azure_openai_chat_deployment,
        )
    return FakeGrounder()


def build_extractor(settings: Settings) -> TextExtractor:
    # DI creds may be empty. That is fine: native PDF extraction works without them, and
    # NativeThenOcrExtractor raises a clear OcrUnavailableError (which the pipeline treats
    # as a permanent failure) if a scanned doc needs OCR while DI is unconfigured — so an
    # unconfigured dev cluster degrades to "digital PDFs only" with an honest error, not a
    # cryptic empty-endpoint network failure retried five times.
    return NativeThenOcrExtractor(
        di_endpoint=settings.azure_documentintelligence_endpoint,
        di_api_key=settings.azure_documentintelligence_api_key,
    )
