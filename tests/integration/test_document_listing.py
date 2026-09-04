"""GET /documents filter/sort/pagination + envelope contract (docs/21 §1.2/§1.3), against
the real docker-compose stack. Also proves the spoke round trip end to end at the API
layer: upload with a spoke -> list filtered by that spoke returns it (the web-proxy half
of the spoke-forwarding bug fix, §1.8, is covered separately by
apps/web/app/api/documents/route.test.ts since apps/web isn't part of this compose stack).
"""

from __future__ import annotations

from conftest import login
from fixtures import make_sample_pdf
from test_e2e_flow import _poll_until_terminal


def test_list_documents_envelope_filter_sort_and_pagination(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-listing")
    headers = {"Authorization": f"Bearer {token}"}

    titles_and_spokes = [
        ("alpha-lease.pdf", "General"),
        ("beta-hoa-rules.pdf", "Legal"),
        ("gamma-notes.pdf", "General"),
    ]
    document_ids: dict[str, str] = {}
    for title, spoke in titles_and_spokes:
        pdf_bytes = make_sample_pdf([title, "Some body text so extraction has something to chunk."])
        upload_response = docs_client.post(
            "/documents",
            files={"file": (title, pdf_bytes, "application/pdf")},
            data={"spoke": spoke},
            headers=headers,
        )
        assert upload_response.status_code == 200, upload_response.text
        document_id = upload_response.json()["document_id"]
        document_ids[title] = document_id
        status = _poll_until_terminal(docs_client, document_id, headers)
        assert status == "indexed", f"expected '{title}' to reach 'indexed', got '{status}'"

    # Envelope shape (§1.2) replaces the old bare array.
    all_response = docs_client.get("/documents", headers=headers)
    assert all_response.status_code == 200, all_response.text
    envelope = all_response.json()
    assert {"items", "total", "limit", "offset"} <= envelope.keys()
    assert envelope["limit"] == 50
    assert envelope["offset"] == 0
    by_id = {d["document_id"]: d for d in envelope["items"]}
    assert set(document_ids.values()) <= by_id.keys()
    assert envelope["total"] >= 3
    assert all(d["origin"] == "uploaded" for d in envelope["items"])

    # With real Azure AI settings, ingestion replaces raw filenames with generated,
    # human-readable titles. With CI's fake/unconfigured providers it preserves the
    # filenames. Capture the post-ingestion values so the list contract is tested in
    # both supported modes rather than treating filenames as permanent titles.
    current_titles = {source: by_id[document_id]["title"] for source, document_id in document_ids.items()}

    # spoke filter: proves the upload's spoke was actually persisted and is filterable —
    # the round trip the web-proxy bug (§1.8) used to break before reaching docs-api.
    legal_response = docs_client.get("/documents", params={"spoke": "Legal"}, headers=headers)
    assert legal_response.status_code == 200
    legal_ids = {d["document_id"] for d in legal_response.json()["items"]}
    assert document_ids["beta-hoa-rules.pdf"] in legal_ids
    assert document_ids["alpha-lease.pdf"] not in legal_ids

    # status filter.
    status_response = docs_client.get("/documents", params={"status": "indexed"}, headers=headers)
    assert status_response.status_code == 200
    assert all(d["current_status"] == "indexed" for d in status_response.json()["items"])

    failed_response = docs_client.get("/documents", params={"status": "failed"}, headers=headers)
    assert failed_response.status_code == 200
    failed_ids = {d["document_id"] for d in failed_response.json()["items"]}
    assert not (set(document_ids.values()) & failed_ids)

    # q filter: case-insensitive substring on title.
    beta_title = current_titles["beta-hoa-rules.pdf"]
    q_response = docs_client.get("/documents", params={"q": beta_title.swapcase()}, headers=headers)
    assert q_response.status_code == 200
    assert document_ids["beta-hoa-rules.pdf"] in {d["document_id"] for d in q_response.json()["items"]}

    # This login owns exactly these three rows, so sort and pagination can compare against
    # the titles actually persisted by the configured provider mode.
    sorted_response = docs_client.get(
        "/documents",
        params={"sort": "title", "order": "asc", "limit": 200},
        headers=headers,
    )
    assert sorted_response.status_code == 200
    ordered_titles = [d["title"] for d in sorted_response.json()["items"]]
    assert ordered_titles == sorted(current_titles.values(), key=str.casefold)

    # pagination: limit=1 walks the same sorted set one row at a time.
    page0 = docs_client.get(
        "/documents",
        params={"sort": "title", "order": "asc", "limit": 1, "offset": 0},
        headers=headers,
    )
    page1 = docs_client.get(
        "/documents",
        params={"sort": "title", "order": "asc", "limit": 1, "offset": 1},
        headers=headers,
    )
    assert page0.json()["items"][0]["title"] == ordered_titles[0]
    assert page1.json()["items"][0]["title"] == ordered_titles[1]
    assert page0.json()["total"] == page1.json()["total"] == 3


def test_list_documents_rejects_invalid_filters(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-listing-400")
    headers = {"Authorization": f"Bearer {token}"}

    assert docs_client.get("/documents", params={"spoke": "Nonexistent"}, headers=headers).status_code == 400
    assert docs_client.get("/documents", params={"status": "not_a_stage"}, headers=headers).status_code == 400
    assert (
        docs_client.get("/documents", params={"origin": "not_an_origin"}, headers=headers).status_code == 400
    )
    assert docs_client.get("/documents", params={"sort": "not_a_column"}, headers=headers).status_code == 400
    assert docs_client.get("/documents", params={"order": "sideways"}, headers=headers).status_code == 400
