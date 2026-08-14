"""build_law_fetchers gating (docs/20 §20.6): CANI_LAW_FETCH_ENABLED must be the only thing
that decides real vs. fake — never inferred from other config being present, since (unlike
Azure AI) there's no credential to infer from. This is the guard against repeating the
fakes-in-prod incident class (CLAUDE.md) for the law corpus.
"""

from __future__ import annotations

from cani_shared.law.fetcher import FakeLawFetcher
from cani_shared.law.sources import SOURCE_REGISTRY
from cani_shared.law.sources.nrs import NrsChapterFetcher
from cani_shared.providers.factory import build_law_fetchers

_VALID_BASE = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "cani",
    "POSTGRES_USER": "cani",
    "POSTGRES_PASSWORD": "a-real-password",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "cani_docs_test",
    "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
    "CANI_TOKEN_SIGNING_SECRET": "x" * 32,
    "CANI_SESSION_SECRET": "y" * 32,
}


def _settings(**overrides):
    from cani_shared.config import Settings

    # _env_file=None: never let a real .env on the dev machine leak
    # CANI_LAW_FETCH_ENABLED into this test (same pattern as test_config.py).
    return Settings(_env_file=None, **{**_VALID_BASE, **overrides})


def test_fetch_disabled_by_default_returns_fakes():
    settings = _settings()

    fetchers = build_law_fetchers(settings)

    assert set(fetchers) == set(SOURCE_REGISTRY)
    assert all(isinstance(f, FakeLawFetcher) for f in fetchers.values())


def test_fetch_enabled_returns_real_fetchers():
    settings = _settings(CANI_LAW_FETCH_ENABLED=True)

    fetchers = build_law_fetchers(settings)

    assert set(fetchers) == set(SOURCE_REGISTRY)
    assert isinstance(fetchers["nrs-116"], NrsChapterFetcher)


def test_fake_fetchers_are_deterministic_and_touch_no_network():
    settings = _settings()
    fetchers = build_law_fetchers(settings)

    doc_one = fetchers["nrs-116"].fetch()
    doc_two = fetchers["nrs-116"].fetch()

    assert doc_one.raw_bytes == doc_two.raw_bytes
    assert [s.citation for s in doc_one.sections] == [s.citation for s in doc_two.sections]
