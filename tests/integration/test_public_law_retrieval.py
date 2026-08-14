"""Phase 2 dual-corpus proof (docs/20-public-law-corpus-design.md §20.10): a Legal-spoke
query against a document collection AND the seeded public-law collection returns citations
of both source kinds, each law citation's snippet is a verbatim substring of the source
statute text, and the yes/no verdict badge is suppressed once law text is cited (Q4).

Seeds the law collection via the ingestion-worker's law_refresh entrypoint running against
FakeLawFetcher + FakeEmbedder (the law_corpus_seeded fixture in conftest.py) — no network,
no live credentials, same philosophy as every other fake provider in this repo.
"""

from __future__ import annotations

import time

import pytest
from conftest import login
from fixtures import make_sample_pdf

# Verbatim per cani_shared.law.fetcher.FakeLawFetcher — the fake corpus's only two
# sections, both well within LAW_CONTEXT_TOP_K (3), so both are always retrieved
# regardless of the (semantically meaningless) fake embedder's scoring.
_NRS_116_001_TEXT = "This chapter may be cited as the Uniform Common-Interest Ownership Act."
_NRS_116_31065_TEXT = (
    "The rules adopted by an association:\n"
    "1. Must be reasonably related to the purpose for which they are adopted.\n"
    "2. Must be sufficiently explicit in their prohibition, direction or "
    "limitation to inform a person of any action or omission required for "
    "compliance.\n"
    "3. Must not be adopted to evade any obligation of the association."
)
_KNOWN_LAW_TEXT_BY_CITATION = {
    "NRS 116.001": _NRS_116_001_TEXT,
    "NRS 116.31065": _NRS_116_31065_TEXT,
}


def _poll_until_terminal(docs_client, document_id: str, headers: dict, timeout_seconds: int = 90) -> str:
    deadline = time.time() + timeout_seconds
    status = "queued"
    while time.time() < deadline:
        response = docs_client.get(f"/documents/{document_id}", headers=headers)
        response.raise_for_status()
        status = response.json()["current_status"]
        if status in ("indexed", "unpacked", "failed"):
            return status
        time.sleep(2)
    pytest.fail(
        f"document {document_id} did not reach a terminal state within {timeout_seconds}s (last: {status})"
    )


def test_legal_spoke_query_cites_both_corpora_and_suppresses_verdict(
    docker_stack, law_corpus_seeded, hub_client, docs_client
):
    token = login(hub_client, "integration-user-public-law")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(
        [
            "HOA COMMON AREA RULES",
            "The board may adopt reasonable rules for the community.",
        ]
    )
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("hoa-rules.pdf", pdf_bytes, "application/pdf")},
        data={"spoke": "Legal"},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]

    status = _poll_until_terminal(docs_client, document_id, headers)
    assert status == "indexed", f"expected document to reach 'indexed', got '{status}'"

    query_response = docs_client.post(
        "/query",
        json={"question": "Are HOA rules required to relate to their purpose?", "spoke": "Legal"},
        headers=headers,
    )
    assert query_response.status_code == 200, query_response.text
    body = query_response.json()

    citations = body["citations"]
    user_citations = [c for c in citations if c["source_kind"] == "user_document"]
    law_citations = [c for c in citations if c["source_kind"] != "user_document"]

    assert user_citations, "expected at least one citation from the user's own document"
    assert user_citations[0]["document_id"] == document_id
    assert user_citations[0]["citation_ref"] is None
    assert user_citations[0]["page_start"] is not None

    # At least one law citation, from the two-section fake corpus (§20.10: "citations of
    # both source kinds"). Exactly which section(s) get cited depends on the grounder — the
    # real Azure OpenAI grounder picks whichever section it judges relevant to the
    # question, while FakeGrounder (no Azure keys configured) always cites every retrieved
    # law chunk — so this asserts presence and correctness, not an exact count.
    assert law_citations, f"expected at least one law citation, got {citations}"
    for citation in law_citations:
        assert citation["source_kind"] == "state_statute"
        assert citation["document_id"] is None
        assert citation["page_start"] is None
        citation_ref = citation["citation_ref"]
        assert citation_ref in _KNOWN_LAW_TEXT_BY_CITATION, citation_ref
        # The verbatim-quote guarantee (docs/20 §20.1 principle 1) as a CI check: the
        # cited snippet must exactly match the source statute text, not a paraphrase.
        assert citation["snippet"] == _KNOWN_LAW_TEXT_BY_CITATION[citation_ref]
        assert citation["source_url"]
        assert citation["law_fetched_at"]

    # Q4 (decided): the yes/no verdict badge is suppressed once any cited chunk is
    # law-sourced, but the citations/quotes/plain-language answer above still render.
    assert body["verdict"] is None, "verdict badge must be suppressed once law text is cited"

    assert "⚖️ Legal Disclaimer" in body["answer"]
    assert "reproduced as fetched" in body["answer"], "law-cited answers get the extended disclaimer sentence"
    # The verbatim-quote guarantee is structural (each law Citation.snippet, asserted
    # exactly above), not a promise that the model's inline prose reproduces the chunk
    # byte-for-byte — a real grounder may lightly reflow whitespace/emphasis when quoting.
    # What the answer text itself must do is name the statute it's drawing from.
    assert any(citation["citation_ref"] in body["answer"] for citation in law_citations), (
        "expected the cited statute's citation to appear directly in the answer text"
    )


def test_general_spoke_query_stays_document_only(docker_stack, law_corpus_seeded, hub_client, docs_client):
    """Same seeded law collection, but the General spoke never opts into it — dual-corpus
    retrieval is scoped to the Legal spoke (or explicit include_public_law) by design."""
    token = login(hub_client, "integration-user-public-law-general")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(["GENERAL NOTES", "Trash pickup is on Tuesdays."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("notes.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]
    status = _poll_until_terminal(docs_client, document_id, headers)
    assert status == "indexed"

    query_response = docs_client.post("/query", json={"question": "When is trash pickup?"}, headers=headers)
    assert query_response.status_code == 200, query_response.text
    body = query_response.json()

    assert all(c["source_kind"] == "user_document" for c in body["citations"])
    assert "⚖️ Legal Disclaimer" not in body["answer"]
