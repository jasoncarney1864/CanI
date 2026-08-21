"""PATCH /documents/{id} (docs/21 follow-up — moving a mis-filed document between spokes),
against the real docker-compose stack: the Documents list reflects the new spoke
immediately, retrieval actually follows the move (not just the Postgres row), ownership is
enforced, and an invalid spoke value is a clean 400.
"""

from __future__ import annotations

from conftest import login
from fixtures import make_sample_pdf
from test_e2e_flow import _poll_until_terminal


def test_move_spoke_updates_document_and_documents_list(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-move-spoke")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(["move-me.pdf", "Body text so extraction has something to chunk."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("move-me.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]
    _poll_until_terminal(docs_client, document_id, headers)

    move_response = docs_client.patch(f"/documents/{document_id}", json={"spoke": "Legal"}, headers=headers)
    assert move_response.status_code == 200, move_response.text
    assert move_response.json()["spoke"] == "Legal"

    legal_list = docs_client.get("/documents?spoke=Legal", headers=headers)
    assert legal_list.status_code == 200
    assert document_id in {d["document_id"] for d in legal_list.json()["items"]}

    general_list = docs_client.get("/documents?spoke=General", headers=headers)
    assert general_list.status_code == 200
    assert document_id not in {d["document_id"] for d in general_list.json()["items"]}


def test_move_spoke_propagates_to_retrieval_not_just_postgres(docker_stack, hub_client, docs_client):
    # The Documents page reads Postgres, but retrieval filters on the Qdrant payload copy
    # of spoke — this is the regression the plain Postgres-only version of this feature
    # would have shipped: the row says "moved" while retrieval still can't find it under
    # the new spoke (or still finds it under the old one).
    token = login(hub_client, "integration-user-move-spoke-retrieval")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(
        ["MOVE-SPOKE RETRIEVAL FIXTURE", "The secret password for this test is XYZZY-PLUGH."]
    )
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("move-spoke-retrieval.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]
    _poll_until_terminal(docs_client, document_id, headers)

    move_response = docs_client.patch(f"/documents/{document_id}", json={"spoke": "Legal"}, headers=headers)
    assert move_response.status_code == 200, move_response.text

    legal_query = docs_client.post(
        "/query", json={"question": "What is the secret password?", "spoke": "Legal"}, headers=headers
    )
    assert legal_query.status_code == 200, legal_query.text
    legal_document_ids = {c["document_id"] for c in legal_query.json()["citations"] if "document_id" in c}
    assert document_id in legal_document_ids, (
        "moved document should be citable once queried under its new spoke — if this "
        "fails, the Postgres row moved but the Qdrant payload didn't"
    )

    general_query = docs_client.post(
        "/query", json={"question": "What is the secret password?", "spoke": "General"}, headers=headers
    )
    assert general_query.status_code == 200, general_query.text
    general_document_ids = {c["document_id"] for c in general_query.json()["citations"] if "document_id" in c}
    assert document_id not in general_document_ids, (
        "moved document should no longer be citable under its old spoke"
    )


def test_move_spoke_unknown_document_is_404(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-move-spoke-404")
    headers = {"Authorization": f"Bearer {token}"}

    response = docs_client.patch(
        "/documents/00000000-0000-0000-0000-000000000000",
        json={"spoke": "Legal"},
        headers=headers,
    )
    assert response.status_code == 404


def test_move_spoke_is_owner_scoped(docker_stack, hub_client, docs_client):
    owner_token = login(hub_client, "integration-user-move-spoke-owner")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    intruder_token = login(hub_client, "integration-user-move-spoke-intruder")
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}

    pdf_bytes = make_sample_pdf(["owner-only-move.pdf", "Body text for extraction."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("owner-only-move.pdf", pdf_bytes, "application/pdf")},
        headers=owner_headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]

    # Same 404 as a nonexistent document — no cross-owner existence leak (§9.8).
    intruder_move = docs_client.patch(
        f"/documents/{document_id}", json={"spoke": "Legal"}, headers=intruder_headers
    )
    assert intruder_move.status_code == 404

    owner_move = docs_client.patch(
        f"/documents/{document_id}", json={"spoke": "Legal"}, headers=owner_headers
    )
    assert owner_move.status_code == 200


def test_move_spoke_rejects_invalid_spoke(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-move-spoke-invalid")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(["invalid-spoke-target.pdf", "Body text for extraction."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("invalid-spoke-target.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]

    response = docs_client.patch(f"/documents/{document_id}", json={"spoke": "NotASpoke"}, headers=headers)
    assert response.status_code == 400
