"""Single place that decides real-vs-fake providers from config, so ingestion-worker and
retrieval-worker always agree on which embedding space is in use. CI and any environment
without Azure AI keys configured automatically fall back to the deterministic fakes —
tests never require live credentials, but local dev with a real .env exercises the real
Azure OpenAI / Document Intelligence path end-to-end.
"""

from __future__ import annotations

from cani_shared.config import Settings
from cani_shared.law.fetcher import FakeLawFetcher, LawSourceFetcher
from cani_shared.law.sources import SOURCE_REGISTRY
from cani_shared.providers.embedder import AzureOpenAIEmbedder, Embedder, FakeEmbedder
from cani_shared.providers.extractor import NativeThenOcrExtractor, TextExtractor
from cani_shared.providers.grounder import AzureOpenAIChatGrounder, ChatGrounder, FakeGrounder
from cani_shared.providers.scanner import ClamAVScanner, EicarSignatureScanner, MalwareScanner


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


def build_malware_scanner(settings: Settings) -> MalwareScanner:
    # Real ClamAV when a daemon is configured; otherwise the EICAR-only dev/CI scanner.
    # The pipeline always scans — this only selects how thorough the backend is.
    if settings.clamav_configured:
        return ClamAVScanner(host=settings.clamav_host, port=settings.clamav_port)
    return EicarSignatureScanner()


def build_law_fetchers(settings: Settings) -> dict[str, LawSourceFetcher]:
    """Real HTTP fetchers when external fetching is enabled; deterministic fakes otherwise,
    so CI and unit tests never touch government websites.

    Unlike every other builder in this module, real-vs-fake here is NOT inferred from
    config presence — there's no credential to check for (NRS is an unauthenticated public
    page), so an inference-based check would have nothing to fail on and would default to
    fake even in prod. That is exactly the shape of the fakes-in-prod incident (CLAUDE.md):
    nothing errors, so nothing gets noticed. `law_fetch_enabled` exists specifically to be
    an explicit switch someone has to flip on purpose, and the refresh job logs
    fetcher_kind=real|fake per run so a silent "still fake" state is visible in logs too.
    """
    if settings.law_fetch_enabled:
        return {key: factory() for key, factory in SOURCE_REGISTRY.items()}
    return {key: FakeLawFetcher(key) for key in SOURCE_REGISTRY}
