from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

from cani_shared.auth.tokens import RequestPrincipal
from cani_shared.models import LegalDraft, LegalTemplate
from docs_api_app import legal
from fastapi import FastAPI
from fastapi.testclient import TestClient

OWNER_ID = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 8, 21, tzinfo=UTC)


class _Pool:
    @contextmanager
    def connection(self):
        yield object()


def _template() -> LegalTemplate:
    return LegalTemplate(
        legal_template_id="template-1",
        slug="reviewed-template",
        version=1,
        title="Reviewed test template",
        category="Legal",
        jurisdiction_note="Test jurisdiction only.",
        field_schema={
            "principal_name": {"type": "text", "label": "Principal", "required": True},
            "notes": {"type": "textarea", "label": "Notes", "required": False},
        },
        body_template="Principal: {principal_name}\nNotes: {notes}",
        disclaimer_text="Not legal advice.",
        is_active=True,
        created_at=NOW,
    )


def _draft(**overrides) -> LegalDraft:
    values = dict(
        legal_draft_id="draft-1",
        owner_user_id=OWNER_ID,
        legal_template_id="template-1",
        template_version=1,
        status="draft",
        field_values_json={},
        document_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(overrides)
    return LegalDraft(**values)


def _client(monkeypatch) -> TestClient:
    principal = RequestPrincipal(user_id=OWNER_ID, entitlements=["docs"])

    def get_principal() -> RequestPrincipal:
        return principal

    def require_docs_entitlement() -> RequestPrincipal:
        return principal

    monkeypatch.setattr(legal, "get_pool", lambda _dsn: _Pool())
    settings = SimpleNamespace(postgres_dsn="postgresql://unused")
    app = FastAPI()
    app.include_router(
        legal.build_legal_router(
            settings=settings,
            get_principal=get_principal,
            require_docs_entitlement=require_docs_entitlement,
        ),
        prefix="/legal",
    )
    return TestClient(app)


def test_inactive_template_is_not_exposed_or_usable(monkeypatch):
    monkeypatch.setattr(legal, "list_active_legal_templates", lambda _conn: [])
    monkeypatch.setattr(legal, "get_active_legal_template", lambda _conn, _slug: None)
    client = _client(monkeypatch)

    assert client.get("/legal/templates").json() == []
    assert client.get("/legal/templates/nv-poa-financial").status_code == 404
    assert client.post("/legal/drafts", json={"template_slug": "nv-poa-financial"}).status_code == 404


def test_create_draft_is_scoped_to_authenticated_owner(monkeypatch):
    captured: dict[str, str | int] = {}
    monkeypatch.setattr(legal, "get_active_legal_template", lambda _conn, _slug: _template())

    def create(_conn, owner_user_id, *, legal_template_id, template_version):
        captured.update(
            owner_user_id=owner_user_id,
            legal_template_id=legal_template_id,
            template_version=template_version,
        )
        return _draft()

    monkeypatch.setattr(legal, "create_legal_draft", create)
    response = _client(monkeypatch).post("/legal/drafts", json={"template_slug": "reviewed-template"})

    assert response.status_code == 201
    assert captured == {
        "owner_user_id": OWNER_ID,
        "legal_template_id": "template-1",
        "template_version": 1,
    }


def test_draft_lookup_does_not_leak_cross_owner_existence(monkeypatch):
    monkeypatch.setattr(legal, "get_legal_draft", lambda _conn, _owner, _draft_id: None)
    response = _client(monkeypatch).get("/legal/drafts/someone-elses-draft")

    assert response.status_code == 404
    assert response.json()["detail"] == "draft not found"


def test_preview_reports_missing_required_fields(monkeypatch):
    monkeypatch.setattr(
        legal,
        "get_legal_draft",
        lambda _conn, _owner, _draft_id: _draft(field_values_json={"notes": "Optional"}),
    )
    monkeypatch.setattr(legal, "get_legal_template", lambda _conn, _template_id: _template())
    response = _client(monkeypatch).get("/legal/drafts/draft-1/preview")

    assert response.status_code == 200
    assert response.json()["missing_required_fields"] == ["principal_name"]
    assert "[not yet provided]" in response.json()["body"]
    assert response.json()["disclaimer_text"] == "Not legal advice."


def test_finalize_is_idempotent_when_document_already_exists(monkeypatch):
    monkeypatch.setattr(
        legal,
        "get_legal_draft",
        lambda _conn, _owner, _draft_id: _draft(status="finalized", document_id="document-1"),
    )
    claim = monkeypatch.setattr(
        legal,
        "claim_legal_draft_for_finalize",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not claim twice")),
    )
    response = _client(monkeypatch).post("/legal/drafts/draft-1/finalize")

    assert claim is None
    assert response.status_code == 200
    assert response.json() == {"document_id": "document-1", "status": "finalized"}
