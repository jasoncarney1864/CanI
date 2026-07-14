# 9. Data model & storage

This section defines where CanI stores each class of data, how records are linked, and how per-user isolation is enforced across metadata, blobs, and vectors.

## 9.1 Goals and constraints

Goals:
- Enforce strict per-user isolation for all reads and writes.
- Keep ingestion and retrieval state queryable and auditable.
- Support deterministic citations (document/page/section/chunk lineage).
- Keep schemas simple enough for a solo operator to run and evolve.

Constraints:
- Qdrant is the accepted vector store (ADR-003).
- PHI/PII-grade posture is default (ADR-007).
- Workloads run in the workload landing zone and private network posture from Section 6.

## 9.2 Storage topology (v1)

Use fit-for-purpose stores rather than a single database for everything.

- Blob Storage: original uploads and extracted artifacts.
- Relational metadata store (PostgreSQL Flexible Server): users/documents/status, ingestion state, citations, and operational metadata.
- Qdrant on AKS: embedding vectors and vector payload metadata for retrieval.

Why this split:
- Blobs are cheap and reliable for large binary/text artifacts.
- Relational schema gives strong consistency for lifecycle and joins.
- Qdrant is optimized for ANN/vector search and already accepted.

## 9.3 Canonical identifiers and ownership fields

Required IDs:
- `user_id`: immutable principal key from Hub identity mapping.
- `document_id`: immutable logical document key.
- `document_version_id`: immutable version key per re-upload or replacement.
- `chunk_id`: immutable retrieval chunk key.
- `ingestion_job_id`: immutable async processing job key.

Ownership rule:
- Every user-scoped row/object/vector must include `owner_user_id`.
- Reads must always scope by `owner_user_id` first, then by resource ID.

## 9.4 Relational metadata schema (PostgreSQL)

Core tables for v1:

1. `documents`
   - Keys: `document_id` (PK), `owner_user_id` (indexed)
   - Fields: title, source_type, current_status, created_at, updated_at, checksum
2. `document_versions`
   - Keys: `document_version_id` (PK), `document_id` (FK), `owner_user_id` (indexed)
   - Fields: blob_uri, extractor_version, extracted_at, page_count, classification_label, classification_confidence
3. `ingestion_jobs`
   - Keys: `ingestion_job_id` (PK), `document_version_id` (FK), `owner_user_id` (indexed)
   - Fields: stage, status, attempt_count, error_code, error_detail, started_at, finished_at
4. `chunk_manifests`
   - Keys: `chunk_id` (PK), `document_version_id` (FK), `owner_user_id` (indexed)
   - Fields: page_start, page_end, section_label, token_count, embedding_version, qdrant_point_id
5. `query_audit`
   - Keys: `query_id` (PK), `owner_user_id` (indexed)
   - Fields: question_hash, model_id, retrieved_chunk_ids, response_status, created_at

Relational guardrails:
- Composite index pattern on `(owner_user_id, document_id)` and `(owner_user_id, document_version_id)`.
- Foreign keys include ownership validation in application logic before write.
- Soft-delete flags for operational safety; hard-delete workflows handled asynchronously.

## 9.5 Blob storage layout and artifact model

Container strategy:
- `raw-documents` for original uploads.
- `extracted-text` for canonical text artifacts.
- `ingestion-artifacts` for OCR JSON/layout outputs and debug bundles.

Path convention:
- `owner_user_id/document_id/document_version_id/<artifact>`

Artifact rules:
- Keep immutable artifacts per version.
- Never overwrite existing extraction outputs in place.
- Metadata DB stores authoritative pointers to blob URIs.

## 9.6 Vector schema in Qdrant

**Decision (v1): one collection per environment/spoke, mandatory payload filtering by owner.**

Payload fields per point:
- `owner_user_id`
- `document_id`
- `document_version_id`
- `chunk_id`
- `page_start`, `page_end`
- `section_label`
- `taxonomy_tags`
- `embedding_version`

Indexing requirements:
- Create payload indexes for `owner_user_id`, `document_id`, and `taxonomy_tags`.
- Every query must include `owner_user_id` as a required filter clause.
- Retrieval path fails closed if owner filter is missing.

## 9.7 Consistency and lifecycle across stores

Write order (ingestion):
1. Create/transition metadata rows first (`documents`, `document_versions`, `ingestion_jobs`).
2. Write blobs and extraction outputs.
3. Create chunk manifest rows.
4. Upsert vectors in Qdrant.
5. Mark version and document as indexed.

Consistency model:
- Eventual consistency between metadata and vectors is acceptable during ingestion.
- Query path only serves versions marked `indexed` in metadata.
- Recovery jobs reconcile metadata rows against missing vector points.

## 9.8 Isolation model and access enforcement

Isolation is layered:
- Hub/spoke authz check (Section 7).
- Metadata queries include owner predicate by default.
- Qdrant queries include mandatory owner payload filter.
- Network policy blocks direct access from non-CanI Docs workloads.

Operational controls:
- Shared support tools must use break-glass workflow and auditable approval for any user-scoped access.
- No broad read role for normal operations.

## 9.9 Retention, deletion, and version history

Retention behavior:
- Preserve document version history for traceability unless user requests deletion.
- Keep query audit records separately with minimized sensitive content.

Deletion behavior:
- User delete request creates a tombstone job.
- Async deleter removes vectors, blob artifacts, and metadata rows in controlled order.
- Emit completion audit event when all store deletions are confirmed.

## 9.10 Backup and restore

- PostgreSQL: automated backups with point-in-time restore enabled.
- Blob Storage: versioning + soft delete enabled for accidental deletion recovery.
- Qdrant: scheduled snapshots exported to Blob Storage.

Restore assumptions:
- Metadata is source of truth for what should be retrievable.
- After Qdrant restore, run reconciliation to verify point counts vs `chunk_manifests`.

## 9.11 v1 implementation checklist

- Provision PostgreSQL schema, indexes, and migration baseline.
- Provision Blob containers with private endpoints and lifecycle policies.
- Define Qdrant collection and payload indexes.
- Implement ownership-scoped repository/query helpers (no unscoped access methods).
- Implement reconciliation job for metadata/vector drift.
- Implement deletion orchestrator with per-store completion checks.

## 9.12 Open questions

1. Should long-term archive versions move to cool/archive storage tiers automatically after inactivity windows?
2. Is one Qdrant collection per spoke enough at v1, or should Legal and Health split early for operational isolation?
3. How long should `query_audit` be retained relative to document content retention?

---

[← RAG pipeline design (CanI Docs)](08-rag-pipeline-design.md) | [Back to index](README.md) | Next: [AKS cluster design →](10-aks-cluster-design.md)