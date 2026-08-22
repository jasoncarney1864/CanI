"""Legal-drafting assistant router (Sprint 4).

Kept as its own APIRouter, built by a factory (build_legal_router) so it can take
main.py's already-constructed auth dependencies (get_principal, require_docs_entitlement)
without a circular import, rather than folding nine more routes into main.py.

Dual-source retrieval (the owner's own Legal-spoke documents + the public-law corpus) is
NOT reimplemented here — retrieval-worker's /retrieve already does it whenever spoke is
"Legal" (retrieval_worker_app.assembly), returning citations pre-labeled by source_kind
("user_document" vs "state_statute"). /converse just calls it, the same way
main.py's own /query does, and reshapes the citations into a field proposal.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from cani_shared.auth.tokens import RequestPrincipal, create_access_token
from cani_shared.blob import RAW_DOCUMENTS_CONTAINER, BlobStore
from cani_shared.config import Settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import (
    claim_legal_draft_for_finalize,
    confirm_legal_draft_fields,
    create_document,
    create_document_version,
    create_ingestion_job,
    create_legal_draft,
    delete_legal_draft,
    get_active_legal_template,
    get_legal_draft,
    get_legal_template,
    list_active_legal_templates,
    set_legal_draft_document_id,
)
from cani_shared.logging import get_logger, hash_user_id
from cani_shared.models import DocumentSpoke, LegalDraft, LegalTemplate, RetrievalAnswer
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from docs_api_app.legal_pdf import render_body_text, render_draft_html, render_pdf_bytes

logger = get_logger(__name__)


class LegalTemplateSummary(BaseModel):
    slug: str
    version: int
    title: str
    category: str
    jurisdiction_note: str
    disclaimer_text: str

    @classmethod
    def from_template(cls, t: LegalTemplate) -> LegalTemplateSummary:
        return cls(
            slug=t.slug,
            version=t.version,
            title=t.title,
            category=t.category,
            jurisdiction_note=t.jurisdiction_note,
            disclaimer_text=t.disclaimer_text,
        )


class LegalTemplateDetail(LegalTemplateSummary):
    field_schema: dict[str, Any]

    @classmethod
    def from_template(cls, t: LegalTemplate) -> LegalTemplateDetail:
        return cls(**LegalTemplateSummary.from_template(t).model_dump(), field_schema=t.field_schema)


class CreateDraftRequest(BaseModel):
    template_slug: str


class ConfirmFieldsRequest(BaseModel):
    fields: dict[str, Any]


class ConverseRequest(BaseModel):
    message: str
    # Which field this turn is trying to fill, if any. Required for the response to carry
    # a proposal — general open-ended chat (no field_key) gets a reply with no proposals.
    field_key: str | None = None


class CitationDTO(BaseModel):
    source_kind: str
    document_id: str | None = None
    document_title: str | None = None
    citation_ref: str | None = None
    snippet: str | None = None


class FieldProposal(BaseModel):
    field_key: str
    value: str
    source: Literal["user_document", "state_statute", "mixed"]
    citations: list[CitationDTO]


class ConverseResponse(BaseModel):
    reply: str
    proposals: list[FieldProposal]


class DraftPreviewResponse(BaseModel):
    body: str
    disclaimer_text: str
    missing_required_fields: list[str]


class FinalizeResponse(BaseModel):
    document_id: str | None
    status: Literal["finalized", "finalize_pending"]


def _require_template(conn, draft: LegalDraft) -> LegalTemplate:
    template = get_legal_template(conn, draft.legal_template_id)
    if template is None:
        # Templates are never hard-deleted (only deactivated), so this should be
        # unreachable in practice — a draft outliving its template's row would be a data
        # bug, not a normal 404.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "template for draft not found")
    return template


def _missing_required_fields(template: LegalTemplate, field_values: dict[str, Any]) -> list[str]:
    return [
        key
        for key, spec in template.field_schema.items()
        if spec.get("required") and not field_values.get(key)
    ]


def build_legal_router(*, settings: Settings, get_principal, require_docs_entitlement) -> APIRouter:
    router = APIRouter()

    def _owned_draft(conn, owner_user_id: str, draft_id: str) -> LegalDraft:
        draft = get_legal_draft(conn, owner_user_id, draft_id)
        if draft is None:
            # Same 404 whether not owned or never existed — no cross-owner existence leak.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
        return draft

    @router.get("/templates", response_model=list[LegalTemplateSummary])
    def list_templates(
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> list[LegalTemplateSummary]:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            templates = list_active_legal_templates(conn)
        return [LegalTemplateSummary.from_template(t) for t in templates]

    @router.get("/templates/{slug}", response_model=LegalTemplateDetail)
    def get_template(
        slug: str,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> LegalTemplateDetail:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            template = get_active_legal_template(conn, slug)
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
        return LegalTemplateDetail.from_template(template)

    @router.post("/drafts", response_model=LegalDraft, status_code=status.HTTP_201_CREATED)
    def create_draft(
        payload: CreateDraftRequest,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> LegalDraft:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            template = get_active_legal_template(conn, payload.template_slug)
            if template is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
            return create_legal_draft(
                conn,
                principal.user_id,
                legal_template_id=template.legal_template_id,
                template_version=template.version,
            )

    @router.get("/drafts/{draft_id}", response_model=LegalDraft)
    def get_draft(
        draft_id: str,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> LegalDraft:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            return _owned_draft(conn, principal.user_id, draft_id)

    @router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_draft(
        draft_id: str,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> None:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            draft = _owned_draft(conn, principal.user_id, draft_id)
            if draft.status != "draft":
                # Already finalized: the resulting document lives on the ordinary
                # Documents page — delete it via DELETE /documents/{id} instead.
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "draft is already finalized; delete the generated document instead",
                )
            delete_legal_draft(conn, principal.user_id, draft_id)

    @router.post("/drafts/{draft_id}/fields/confirm", response_model=LegalDraft)
    def confirm_fields(
        draft_id: str,
        payload: ConfirmFieldsRequest,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> LegalDraft:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            existing = _owned_draft(conn, principal.user_id, draft_id)
            if existing.status != "draft":
                raise HTTPException(status.HTTP_409_CONFLICT, "draft is already finalized")
            updated = confirm_legal_draft_fields(conn, principal.user_id, draft_id, payload.fields)
        assert updated is not None  # just verified status == 'draft' inside the same call
        return updated

    @router.get("/drafts/{draft_id}/preview", response_model=DraftPreviewResponse)
    def preview_draft(
        draft_id: str,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> DraftPreviewResponse:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            draft = _owned_draft(conn, principal.user_id, draft_id)
            template = _require_template(conn, draft)
        return DraftPreviewResponse(
            body=render_body_text(template.body_template, draft.field_values_json),
            disclaimer_text=template.disclaimer_text,
            missing_required_fields=_missing_required_fields(template, draft.field_values_json),
        )

    @router.post("/drafts/{draft_id}/converse", response_model=ConverseResponse)
    async def converse(
        draft_id: str,
        payload: ConverseRequest,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> ConverseResponse:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            draft = _owned_draft(conn, principal.user_id, draft_id)
            template = _require_template(conn, draft)

        field_label = None
        if payload.field_key is not None:
            field_spec = template.field_schema.get(payload.field_key)
            if field_spec is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown field: {payload.field_key}")
            field_label = field_spec.get("label", payload.field_key)

        # Nothing here is saved to field_values_json — only POST .../fields/confirm writes
        # it. This call only proposes.
        question = f"{field_label}: {payload.message}" if field_label else payload.message
        internal_token = create_access_token(
            user_id=principal.user_id,
            entitlements=principal.entitlements,
            secret=settings.cani_token_signing_secret,
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.retrieval_worker_url}/retrieve",
                # spoke="Legal" is what makes retrieval-worker blend the owner's own
                # Legal-spoke documents with the public-law corpus (assembly.py) — the
                # entire "dual-source retrieval" requirement, already built for /query.
                json={
                    "question": question,
                    "spoke": "Legal",
                    "include_public_law": True,
                    "jurisdictions": None,
                },
                headers={"Authorization": f"Bearer {internal_token}"},
            )
        if response.status_code != 200:
            logger.error("legal_converse_retrieval_error", status_code=response.status_code)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "retrieval service error")
        answer = RetrievalAnswer.model_validate(response.json())

        proposals: list[FieldProposal] = []
        if payload.field_key is not None and not answer.insufficient_evidence and answer.citations:
            source_kinds = {c.source_kind for c in answer.citations}
            source: Literal["user_document", "state_statute", "mixed"] = (
                "mixed"
                if len(source_kinds) > 1
                else ("user_document" if "user_document" in source_kinds else "state_statute")
            )
            proposals.append(
                FieldProposal(
                    field_key=payload.field_key,
                    value=answer.answer,
                    source=source,
                    citations=[
                        CitationDTO(
                            source_kind=c.source_kind,
                            document_id=c.document_id,
                            document_title=c.document_title,
                            citation_ref=c.citation_ref,
                            snippet=c.snippet,
                        )
                        for c in answer.citations
                    ],
                )
            )
        return ConverseResponse(reply=answer.answer, proposals=proposals)

    @router.post("/drafts/{draft_id}/finalize", response_model=FinalizeResponse)
    def finalize_draft(
        draft_id: str,
        request: Request,
        principal: RequestPrincipal = Depends(get_principal),
        _: RequestPrincipal = Depends(require_docs_entitlement),
    ) -> FinalizeResponse:
        pool = get_pool(settings.postgres_dsn)
        with pool.connection() as conn:
            existing = _owned_draft(conn, principal.user_id, draft_id)
            if existing.document_id is not None:
                # Already finalized — duplicate call, return the same document rather than
                # creating a second one.
                return FinalizeResponse(document_id=existing.document_id, status="finalized")

            claimed = claim_legal_draft_for_finalize(conn, principal.user_id, draft_id)
            if claimed is None:
                # Lost the race: another finalize call claimed it between our read above
                # and now, and hasn't set document_id yet. Tell the caller to poll rather
                # than block — same shape as DELETE /documents/{id}'s 202 pending.
                return FinalizeResponse(document_id=None, status="finalize_pending")

            template = _require_template(conn, claimed)
            generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            html_content = render_draft_html(
                template=template, field_values=claimed.field_values_json, generated_at=generated_at
            )
            pdf_bytes = render_pdf_bytes(html_content)
            checksum = hashlib.sha256(pdf_bytes).hexdigest()

            document = create_document(
                conn,
                principal.user_id,
                title=template.title,
                source_type="application/pdf",
                checksum=checksum,
                spoke=DocumentSpoke.LEGAL,
                origin="generated",
                generated_from={
                    "kind": "legal_draft",
                    "legal_draft_id": draft_id,
                    "template_slug": template.slug,
                    "template_version": template.version,
                },
            )
            blob_store: BlobStore = request.app.state.blob_store
            document_version_id = str(uuid.uuid4())
            blob_path = BlobStore.artifact_path(
                principal.user_id, document.document_id, document_version_id, "original.pdf"
            )
            blob_uri = blob_store.upload(container=RAW_DOCUMENTS_CONTAINER, path=blob_path, data=pdf_bytes)
            document_version = create_document_version(
                conn,
                principal.user_id,
                document.document_id,
                blob_uri=blob_uri,
                document_version_id=document_version_id,
            )
            create_ingestion_job(conn, principal.user_id, document_version.document_version_id)
            set_legal_draft_document_id(conn, principal.user_id, draft_id, document.document_id)

        logger.info(
            "legal_draft_finalized",
            draft_id=draft_id,
            document_id=document.document_id,
            user_id_hash=hash_user_id(principal.user_id),
        )
        return FinalizeResponse(document_id=document.document_id, status="finalized")

    return router
