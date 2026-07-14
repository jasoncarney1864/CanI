"""Full core-loop proof: auth -> upload -> ingest -> retrieve -> cite, against the real
docker-compose dev stack (docs/16 Milestone A: "Upload-to-answer path works end-to-end").
"""

from __future__ import annotations

import time

import pytest
from conftest import login
from fixtures import make_sample_pdf


def test_upload_ingest_retrieve_cite(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-a")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(
        [
            "HOA COMMON AREA RULES",
            "Dogs must be leashed after 9pm in all common areas.",
            "Quiet hours begin at 10pm nightly on weekdays.",
        ]
    )
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("hoa-rules.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]

    status = _poll_until_terminal(docs_client, document_id, headers)
    assert status == "indexed", f"expected document to reach 'indexed', got '{status}'"

    query_response = docs_client.post(
        "/query", json={"question": "When must dogs be leashed?"}, headers=headers
    )
    assert query_response.status_code == 200, query_response.text
    body = query_response.json()

    assert body["citations"], "expected at least one citation for a question answerable from the uploaded doc"
    assert body["citations"][0]["document_id"] == document_id


def _poll_until_terminal(docs_client, document_id: str, headers: dict, timeout_seconds: int = 90) -> str:
    deadline = time.time() + timeout_seconds
    status = "queued"
    while time.time() < deadline:
        response = docs_client.get(f"/documents/{document_id}", headers=headers)
        response.raise_for_status()
        status = response.json()["current_status"]
        if status in ("indexed", "failed"):
            return status
        time.sleep(2)
    pytest.fail(
        f"document {document_id} did not reach a terminal state within {timeout_seconds}s (last: {status})"
    )
