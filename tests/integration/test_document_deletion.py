"""DELETE /documents/{id} (docs/09 §9.9, docs/21 §1.4/§1.7), against the real
docker-compose stack. Deletion is a synchronous tombstone + an async cleanup job; what's
verifiable from the black-box API is the synchronous half (list/get/text exclusion,
dedupe clearing so a re-upload isn't silently merged into the tombstoned document) plus
the endpoint's ownership and idempotency contract. The async cleanup itself (Qdrant point
removal, blob removal, final row deletes) is covered by
tests/unit/test_deletion_failure.py and tests/unit/test_blob_delete_prefix.py — there is
no public endpoint that exposes deletion_jobs completion to poll on.
"""

from __future__ import annotations

from conftest import login
from fixtures import make_sample_pdf
from test_e2e_flow import _poll_until_terminal


def test_delete_tombstones_and_clears_dedupe(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-delete")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(["delete-me.pdf", "Some body text so extraction has something to chunk."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("delete-me.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]
    status = _poll_until_terminal(docs_client, document_id, headers)
    assert status == "indexed", f"expected 'delete-me.pdf' to reach 'indexed', got '{status}'"

    delete_response = docs_client.delete(f"/documents/{document_id}", headers=headers)
    assert delete_response.status_code == 202, delete_response.text
    assert delete_response.json() == {"document_id": document_id, "status": "delete_pending"}

    # Synchronous half: gone from list/get/text immediately, before any async cleanup runs.
    list_response = docs_client.get("/documents", headers=headers)
    assert document_id not in {d["document_id"] for d in list_response.json()["items"]}

    get_response = docs_client.get(f"/documents/{document_id}", headers=headers)
    assert get_response.status_code == 404

    text_response = docs_client.get(f"/documents/{document_id}/text", headers=headers)
    assert text_response.status_code == 404

    # Idempotent: a second delete of an already-tombstoned document is still 202, not 404,
    # and must not error even before the first job's cleanup has run (§1.4 step 2).
    second_delete = docs_client.delete(f"/documents/{document_id}", headers=headers)
    assert second_delete.status_code == 202
    assert second_delete.json()["status"] == "delete_pending"

    # Dedupe cleared: checksum lookup excludes tombstoned rows, so re-uploading the exact
    # same bytes creates a fresh document rather than being merged into the deleted one.
    reupload_response = docs_client.post(
        "/documents",
        files={"file": ("delete-me.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert reupload_response.status_code == 200, reupload_response.text
    new_document_id = reupload_response.json()["document_id"]
    assert new_document_id != document_id
    new_status = _poll_until_terminal(docs_client, new_document_id, headers)
    assert new_status == "indexed"


def test_delete_unknown_document_is_404(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-delete-404")
    headers = {"Authorization": f"Bearer {token}"}

    response = docs_client.delete("/documents/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_delete_is_owner_scoped(docker_stack, hub_client, docs_client):
    owner_token = login(hub_client, "integration-user-delete-owner")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    intruder_token = login(hub_client, "integration-user-delete-intruder")
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}

    pdf_bytes = make_sample_pdf(["owner-only.pdf", "Body text for extraction."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("owner-only.pdf", pdf_bytes, "application/pdf")},
        headers=owner_headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]

    # A different owner deleting someone else's document must get the same 404 as a
    # nonexistent document — no cross-owner existence leak (§9.8).
    intruder_delete = docs_client.delete(f"/documents/{document_id}", headers=intruder_headers)
    assert intruder_delete.status_code == 404

    # Unaffected by the failed cross-owner attempt.
    get_response = docs_client.get(f"/documents/{document_id}", headers=owner_headers)
    assert get_response.status_code == 200
