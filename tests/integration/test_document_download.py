"""GET /documents/{id}/original (docs/21 §2.2), against the real docker-compose stack:
downloaded bytes match the uploaded bytes, headers are correct, ownership is enforced,
and a missing document is a clean 404.
"""

from __future__ import annotations

from conftest import login
from fixtures import make_sample_pdf
from test_e2e_flow import _poll_until_terminal


def test_download_returns_original_bytes_and_headers(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-download")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(["download-me.pdf", "Some body text so extraction has something to chunk."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("download-me.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]
    status = _poll_until_terminal(docs_client, document_id, headers)
    assert status == "indexed", f"expected 'download-me.pdf' to reach 'indexed', got '{status}'"

    download_response = docs_client.get(f"/documents/{document_id}/original", headers=headers)
    assert download_response.status_code == 200
    assert download_response.content == pdf_bytes
    assert download_response.headers["content-type"] == "application/pdf"
    disposition = download_response.headers["content-disposition"]
    assert "attachment" in disposition
    assert ".pdf" in disposition


def test_download_unknown_document_is_404(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-download-404")
    headers = {"Authorization": f"Bearer {token}"}

    response = docs_client.get("/documents/00000000-0000-0000-0000-000000000000/original", headers=headers)
    assert response.status_code == 404


def test_download_is_owner_scoped(docker_stack, hub_client, docs_client):
    owner_token = login(hub_client, "integration-user-download-owner")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    intruder_token = login(hub_client, "integration-user-download-intruder")
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}

    pdf_bytes = make_sample_pdf(["owner-only-dl.pdf", "Body text for extraction."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("owner-only-dl.pdf", pdf_bytes, "application/pdf")},
        headers=owner_headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]

    # Same 404 as a nonexistent document — no cross-owner existence leak (§9.8).
    intruder_download = docs_client.get(f"/documents/{document_id}/original", headers=intruder_headers)
    assert intruder_download.status_code == 404

    owner_download = docs_client.get(f"/documents/{document_id}/original", headers=owner_headers)
    assert owner_download.status_code == 200
    assert owner_download.content == pdf_bytes


def test_download_after_delete_is_404(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-download-deleted")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = make_sample_pdf(["delete-then-download.pdf", "Body text for extraction."])
    upload_response = docs_client.post(
        "/documents",
        files={"file": ("delete-then-download.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    document_id = upload_response.json()["document_id"]
    _poll_until_terminal(docs_client, document_id, headers)

    delete_response = docs_client.delete(f"/documents/{document_id}", headers=headers)
    assert delete_response.status_code == 202

    # Tombstoned documents are invisible to every deleted_at-filtered query, including
    # the download endpoint's get_document lookup — same 404 as never-existed (§9.8).
    download_response = docs_client.get(f"/documents/{document_id}/original", headers=headers)
    assert download_response.status_code == 404
