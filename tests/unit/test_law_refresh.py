"""Refresh diff logic (docs/20 §20.7, §20.10): unchanged sections skip re-embedding,
changed/new sections reuse a deterministic point id so the upsert replaces in place, and
sections that disappear from a fetch get deleted from Qdrant. No real Postgres/Qdrant/network
— repository calls are monkeypatched and the embedder/qdrant are fakes/mocks that record
what they were asked to do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from cani_shared.law.models import FetchedLawDocument, LawSection
from cani_shared.models import LawChunkManifest, LawSource, LawSourceVersion
from cani_shared.providers.embedder import FakeEmbedder
from ingestion_worker_app import law_refresh
from ingestion_worker_app.law_refresh import _point_id, refresh_source


def _source() -> LawSource:
    return LawSource(
        law_source_id="src-1",
        source_key="nrs-116",
        display_name="Nevada Revised Statutes, Chapter 116",
        source_kind="state_statute",
        jurisdiction="us-nv",
        citation_prefix="NRS 116",
        fetch_url="https://www.leg.state.nv.us/NRS/NRS-116.html",
        license_note="Public record.",
        enabled=True,
        created_at=datetime.now(UTC),
    )


class _StubFetcher:
    def __init__(self, sections: list[LawSection], raw_bytes: bytes = b"raw-v1"):
        self.source_key = "nrs-116"
        self._sections = sections
        self._raw_bytes = raw_bytes

    def fetch(self) -> FetchedLawDocument:
        return FetchedLawDocument(
            raw_bytes=self._raw_bytes, content_type="text/html", sections=self._sections
        )


def _two_sections() -> list[LawSection]:
    return [
        LawSection(
            citation="NRS 116.001",
            heading="Short title.",
            text="This chapter may be cited as the Act.",
            source_url="https://example.test#001",
            order=0,
        ),
        LawSection(
            citation="NRS 116.003",
            heading="Definitions.",
            text="Words used in this chapter have the meanings ascribed to them.",
            source_url="https://example.test#003",
            order=1,
        ),
    ]


@pytest.fixture
def repo(monkeypatch):
    mocks = MagicMock()
    mocks.get_latest_law_source_version.return_value = None
    mocks.get_latest_law_chunk_manifests.return_value = []
    for name in (
        "get_latest_law_source_version",
        "get_latest_law_chunk_manifests",
        "create_law_source_version",
        "replace_law_chunk_manifests",
        "update_law_source_version_status",
        "touch_law_source_checked",
    ):
        monkeypatch.setattr(law_refresh, name, getattr(mocks, name))
    return mocks


@pytest.fixture
def blob_store():
    store = MagicMock()
    store.upload.return_value = "public-law-snapshots/nrs-116/v1/raw.html"
    return store


@pytest.fixture
def qdrant():
    return MagicMock()


def test_first_refresh_embeds_and_upserts_every_chunk(repo, blob_store, qdrant):
    source = _source()
    fetcher = _StubFetcher(_two_sections())
    embedder = FakeEmbedder()

    refresh_source(
        MagicMock(),
        source,
        fetcher=fetcher,
        blob_store=blob_store,
        embedder=embedder,
        qdrant=qdrant,
        fetcher_kind="fake",
    )

    assert qdrant.upsert_section.call_count == 2
    assert qdrant.delete_points.call_count == 0
    repo.replace_law_chunk_manifests.assert_called_once()
    manifests = repo.replace_law_chunk_manifests.call_args.args[2]
    assert {m.citation for m in manifests} == {"NRS 116.001", "NRS 116.003"}
    repo.update_law_source_version_status.assert_called_once()
    repo.touch_law_source_checked.assert_called_once()


def test_unchanged_source_checksum_skips_everything(repo, blob_store, qdrant):
    source = _source()
    raw_bytes = b"same-bytes"
    fetcher = _StubFetcher(_two_sections(), raw_bytes=raw_bytes)
    embedder = FakeEmbedder()
    import hashlib

    repo.get_latest_law_source_version.return_value = LawSourceVersion(
        law_source_version_id="v0",
        law_source_id="src-1",
        fetched_at=datetime.now(UTC),
        blob_uri="public-law-snapshots/nrs-116/v0/raw.html",
        checksum=hashlib.sha256(raw_bytes).hexdigest(),
        section_count=2,
        status="indexed",
    )

    refresh_source(
        MagicMock(),
        source,
        fetcher=fetcher,
        blob_store=blob_store,
        embedder=embedder,
        qdrant=qdrant,
        fetcher_kind="fake",
    )

    qdrant.upsert_section.assert_not_called()
    blob_store.upload.assert_not_called()
    repo.replace_law_chunk_manifests.assert_not_called()
    repo.touch_law_source_checked.assert_called_once()


def test_unchanged_section_content_is_not_reembedded(repo, blob_store, qdrant):
    source = _source()
    sections = _two_sections()
    fetcher = _StubFetcher(sections)
    embedder = FakeEmbedder()

    point_id_001 = _point_id("nrs-116", "NRS 116.001", 0)
    point_id_003 = _point_id("nrs-116", "NRS 116.003", 0)
    content_hash_001 = __import__("hashlib").sha256(sections[0].text.encode("utf-8")).hexdigest()

    repo.get_latest_law_chunk_manifests.return_value = [
        LawChunkManifest(
            chunk_id=point_id_001,
            law_source_version_id="v0",
            law_source_id="src-1",
            citation="NRS 116.001",
            heading="Short title.",
            source_url="https://example.test#001",
            chunk_index=0,
            token_count=10,
            content_sha256=content_hash_001,
            embedding_version=embedder.embedding_version,
            qdrant_point_id=point_id_001,
        )
    ]

    refresh_source(
        MagicMock(),
        source,
        fetcher=fetcher,
        blob_store=blob_store,
        embedder=embedder,
        qdrant=qdrant,
        fetcher_kind="fake",
    )

    # Only 116.003 (new/changed) gets embedded+upserted; 116.001's content is unchanged.
    assert qdrant.upsert_section.call_count == 1
    upserted_point_id = qdrant.upsert_section.call_args.kwargs["point_id"]
    assert upserted_point_id == point_id_003

    manifests = repo.replace_law_chunk_manifests.call_args.args[2]
    assert {m.citation for m in manifests} == {"NRS 116.001", "NRS 116.003"}
    reused = next(m for m in manifests if m.citation == "NRS 116.001")
    assert reused.qdrant_point_id == point_id_001
    assert reused.content_sha256 == content_hash_001


def test_content_change_reembeds_with_same_deterministic_point_id(repo, blob_store, qdrant):
    source = _source()
    sections = _two_sections()
    fetcher = _StubFetcher(sections)
    embedder = FakeEmbedder()

    point_id_001 = _point_id("nrs-116", "NRS 116.001", 0)
    stale_hash = "not-the-current-hash"

    repo.get_latest_law_chunk_manifests.return_value = [
        LawChunkManifest(
            chunk_id=point_id_001,
            law_source_version_id="v0",
            law_source_id="src-1",
            citation="NRS 116.001",
            heading="Short title.",
            source_url="https://example.test#001",
            chunk_index=0,
            token_count=10,
            content_sha256=stale_hash,
            embedding_version=embedder.embedding_version,
            qdrant_point_id=point_id_001,
        )
    ]

    refresh_source(
        MagicMock(),
        source,
        fetcher=fetcher,
        blob_store=blob_store,
        embedder=embedder,
        qdrant=qdrant,
        fetcher_kind="fake",
    )

    upserted_point_ids = {call.kwargs["point_id"] for call in qdrant.upsert_section.call_args_list}
    assert point_id_001 in upserted_point_ids  # re-embedded, but point id is unchanged (replace-in-place)


def test_embedder_version_change_forces_reembed_even_if_content_hash_matches(repo, blob_store, qdrant):
    source = _source()
    sections = _two_sections()
    fetcher = _StubFetcher(sections)
    embedder = FakeEmbedder()

    point_id_001 = _point_id("nrs-116", "NRS 116.001", 0)
    content_hash_001 = __import__("hashlib").sha256(sections[0].text.encode("utf-8")).hexdigest()

    repo.get_latest_law_chunk_manifests.return_value = [
        LawChunkManifest(
            chunk_id=point_id_001,
            law_source_version_id="v0",
            law_source_id="src-1",
            citation="NRS 116.001",
            heading="Short title.",
            source_url="https://example.test#001",
            chunk_index=0,
            token_count=10,
            content_sha256=content_hash_001,
            embedding_version="some-older-embedder-v0",  # different from embedder.embedding_version
            qdrant_point_id=point_id_001,
        )
    ]

    refresh_source(
        MagicMock(),
        source,
        fetcher=fetcher,
        blob_store=blob_store,
        embedder=embedder,
        qdrant=qdrant,
        fetcher_kind="fake",
    )

    upserted_point_ids = {call.kwargs["point_id"] for call in qdrant.upsert_section.call_args_list}
    assert point_id_001 in upserted_point_ids


def test_removed_citation_is_deleted_from_qdrant(repo, blob_store, qdrant):
    source = _source()
    # Fetch now only returns 116.001 — 116.003 has been repealed/removed.
    sections = [_two_sections()[0]]
    fetcher = _StubFetcher(sections)
    embedder = FakeEmbedder()

    point_id_003 = _point_id("nrs-116", "NRS 116.003", 0)
    repo.get_latest_law_chunk_manifests.return_value = [
        LawChunkManifest(
            chunk_id=point_id_003,
            law_source_version_id="v0",
            law_source_id="src-1",
            citation="NRS 116.003",
            heading="Definitions.",
            source_url="https://example.test#003",
            chunk_index=1,
            token_count=10,
            content_sha256="whatever",
            embedding_version=embedder.embedding_version,
            qdrant_point_id=point_id_003,
        )
    ]

    refresh_source(
        MagicMock(),
        source,
        fetcher=fetcher,
        blob_store=blob_store,
        embedder=embedder,
        qdrant=qdrant,
        fetcher_kind="fake",
    )

    qdrant.delete_points.assert_called_once()
    deleted_ids = qdrant.delete_points.call_args.args[0]
    assert deleted_ids == [point_id_003]

    manifests = repo.replace_law_chunk_manifests.call_args.args[2]
    assert {m.citation for m in manifests} == {"NRS 116.001"}


def test_point_id_is_deterministic_and_stable_across_calls():
    assert _point_id("nrs-116", "NRS 116.001", 0) == _point_id("nrs-116", "NRS 116.001", 0)
    assert _point_id("nrs-116", "NRS 116.001", 0) != _point_id("nrs-116", "NRS 116.003", 0)
    assert _point_id("nrs-116", "NRS 116.001", 0) != _point_id("nrs-116", "NRS 116.001", 1)
