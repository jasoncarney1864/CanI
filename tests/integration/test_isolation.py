"""Negative test proving tenant isolation (docs/16 Milestone A: "No known cross-user
access path in validation tests"). User B must never see User A's chunks or citations,
even when asking about the exact same content, even though both hit the same shared
Qdrant collection and Postgres tables.
"""

from __future__ import annotations

import httpx
from conftest import HUB_URL, login
from fixtures import make_sample_pdf
from test_e2e_flow import _poll_until_terminal


def test_cross_user_isolation(docker_stack, hub_client, docs_client):
    token_a = login(hub_client, "integration-user-a-isolation")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    pdf_bytes = make_sample_pdf(
        ["CONFIDENTIAL ACCESS CODE", "The garage door code is 4471 and must not be shared."]
    )
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("secret.pdf", pdf_bytes, "application/pdf")},
        headers=headers_a,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]
    status = _poll_until_terminal(docs_client, document_id, headers_a)
    assert status == "indexed"

    with httpx.Client(base_url=HUB_URL, timeout=30.0) as hub_client_b:
        token_b = login(hub_client_b, "integration-user-b-isolation")

    query_response = docs_client.post(
        "/query",
        json={"question": "What is the garage door code?"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert query_response.status_code == 200, query_response.text
    body = query_response.json()

    assert not body["citations"], "user B must receive zero citations into user A's document"
    assert not any(c["document_id"] == document_id for c in body["citations"])
    assert body["insufficient_evidence"] is True
