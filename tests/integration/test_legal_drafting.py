"""Legal-drafting activation boundary against the migrated compose stack.

Migration 0008 deliberately seeds the unreviewed Nevada POA inactive. The public API must
therefore expose neither the template nor a way to create a draft from its known slug.
"""

from __future__ import annotations

from conftest import login


def test_unreviewed_nevada_template_stays_dark(docker_stack, hub_client, docs_client):
    token = login(hub_client, "integration-user-legal")
    headers = {"Authorization": f"Bearer {token}"}

    templates = docs_client.get("/legal/templates", headers=headers)
    assert templates.status_code == 200, templates.text
    assert all(template["slug"] != "nv-poa-financial" for template in templates.json())

    detail = docs_client.get("/legal/templates/nv-poa-financial", headers=headers)
    assert detail.status_code == 404, detail.text

    create = docs_client.post(
        "/legal/drafts",
        json={"template_slug": "nv-poa-financial"},
        headers=headers,
    )
    assert create.status_code == 404, create.text
