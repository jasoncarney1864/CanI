"""POST /documents/generated (docs/21 §3), against the real docker-compose stack: a saved
answer appears on the Documents page with origin=generated, flows through the ordinary
ingestion pipeline to 'indexed', its extracted text excludes the front matter, and it
downloads back as the .md file that was written.
"""

from __future__ import annotations

from conftest import login
from test_e2e_flow import _poll_until_terminal


def _generated_payload(question: str, spoke: str = "Legal") -> dict:
    return {
        "title": None,
        "spoke": spoke,
        "markdown": "# Can I sublet my unit?\n\nYes, with board approval.",
        "provenance": {
            "question": question,
            "model_id": "claude-sonnet-5",
            "citations": [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "document_title": "HOA Rules",
                    "citation_ref": None,
                }
            ],
        },
    }


def test_generated_document_reaches_indexed_and_lists_with_origin(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-generated")
    headers = {"Authorization": f"Bearer {token}"}

    create_response = docs_client.post(
        "/documents/generated", json=_generated_payload("Can I sublet my unit?"), headers=headers
    )
    assert create_response.status_code == 200, create_response.text
    body = create_response.json()
    document_id = body["document_id"]
    assert body["status"] == "queued"

    status = _poll_until_terminal(docs_client, document_id, headers)
    assert status == "indexed", f"expected the generated document to reach 'indexed', got '{status}'"

    list_response = docs_client.get("/documents?origin=generated", headers=headers)
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    matching = [d for d in items if d["document_id"] == document_id]
    assert len(matching) == 1
    assert matching[0]["origin"] == "generated"
    assert matching[0]["spoke"] == "Legal"
    # generated_from is deliberately excluded from the list envelope (§3.2).
    assert "generated_from" not in matching[0]

    get_response = docs_client.get(f"/documents/{document_id}", headers=headers)
    assert get_response.status_code == 200
    single = get_response.json()
    assert single["origin"] == "generated"
    assert single["generated_from"]["question"] == "Can I sublet my unit?"


def test_generated_document_text_excludes_front_matter(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-generated-text")
    headers = {"Authorization": f"Bearer {token}"}

    create_response = docs_client.post(
        "/documents/generated", json=_generated_payload("What does section 7.2 say?"), headers=headers
    )
    assert create_response.status_code == 200, create_response.text
    document_id = create_response.json()["document_id"]
    status = _poll_until_terminal(docs_client, document_id, headers)
    assert status == "indexed"

    text_response = docs_client.get(f"/documents/{document_id}/text", headers=headers)
    assert text_response.status_code == 200
    chunks = text_response.json()["chunks"]
    full_text = "\n".join(c["text"] for c in chunks)
    assert "generated_at:" not in full_text
    assert "provenance" not in full_text.lower()
    assert "Can I sublet my unit?" in full_text  # the markdown body itself, not the front matter


def test_generated_document_downloads_as_markdown(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-generated-download")
    headers = {"Authorization": f"Bearer {token}"}

    create_response = docs_client.post(
        "/documents/generated", json=_generated_payload("Download me"), headers=headers
    )
    assert create_response.status_code == 200, create_response.text
    document_id = create_response.json()["document_id"]
    _poll_until_terminal(docs_client, document_id, headers)

    download_response = docs_client.get(f"/documents/{document_id}/original", headers=headers)
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "text/markdown"
    assert ".md" in download_response.headers["content-disposition"]
    body_text = download_response.content.decode("utf-8")
    assert body_text.startswith("---\n")
    assert "Can I sublet my unit?" in body_text


def test_generated_document_request_validation_errors_are_400(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-generated-validation")
    headers = {"Authorization": f"Bearer {token}"}

    too_long_title = "x" * 201
    response = docs_client.post(
        "/documents/generated",
        json={**_generated_payload("q"), "title": too_long_title},
        headers=headers,
    )
    assert response.status_code == 400
    assert "title" in response.json()["detail"]

    empty_markdown = {**_generated_payload("q"), "markdown": ""}
    response = docs_client.post("/documents/generated", json=empty_markdown, headers=headers)
    assert response.status_code == 400
    assert "markdown" in response.json()["detail"]

    bad_spoke = {**_generated_payload("q"), "spoke": "NotASpoke"}
    response = docs_client.post("/documents/generated", json=bad_spoke, headers=headers)
    assert response.status_code == 400
    assert "spoke" in response.json()["detail"]
