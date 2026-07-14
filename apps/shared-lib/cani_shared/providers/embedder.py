"""Embedding generation per docs/08-rag-pipeline-design.md §8.7: single embedding model
per environment, recorded as embedding_version on every chunk to avoid vector-space drift.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

EMBEDDING_VERSION_FAKE = "fake-v1-384"


class Embedder(ABC):
    @property
    @abstractmethod
    def embedding_version(self) -> str: ...

    @property
    @abstractmethod
    def vector_size(self) -> int: ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class AzureOpenAIEmbedder(Embedder):
    """Real implementation, calls Azure OpenAI embeddings deployment."""

    _VECTOR_SIZE = 1536  # text-embedding-3-small dimensionality

    def __init__(self, *, endpoint: str, api_key: str, api_version: str, deployment: str):
        from openai import AzureOpenAI

        self._client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        self._deployment = deployment

    @property
    def embedding_version(self) -> str:
        return f"azure-openai:{self._deployment}"

    @property
    def vector_size(self) -> int:
        return self._VECTOR_SIZE

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._deployment, input=texts)
        return [item.embedding for item in response.data]


class FakeEmbedder(Embedder):
    """Deterministic, hash-based embedding for unit tests — no network calls, no real
    semantic meaning, but stable across runs so retrieval-ordering tests are reproducible."""

    _VECTOR_SIZE = 32

    @property
    def embedding_version(self) -> str:
        return EMBEDDING_VERSION_FAKE

    @property
    def vector_size(self) -> int:
        return self._VECTOR_SIZE

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[: self._VECTOR_SIZE]]
