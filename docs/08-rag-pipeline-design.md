# 8. RAG pipeline design (CanI Docs)

This section defines the end-to-end ingestion and retrieval flow for CanI Docs, including OCR/parsing, chunking, embeddings, retrieval, grounding, and citation behavior.

## 8.1 Goals and non-goals

Goals:
- Answer only from user-owned source documents.
- Return explicit citations for each material claim.
- Keep ingestion resilient to partial failures and retries.
- Enforce ownership filters before and during retrieval.

Non-goals for v1:
- Full legal or medical reasoning beyond document-grounded interpretation.
- Cross-user corpus search.
- Real-time streaming ingestion for very large enterprise archives.

## 8.2 Pipeline overview

The pipeline is asynchronous after upload.

1. User uploads document/image to CanI Docs.
2. Upload service stores original file in private Blob Storage and creates a document job record.
3. Ingestion worker extracts text (and OCR where needed), normalizes content, and stores extracted artifacts.
4. Chunking worker creates retrieval chunks and metadata.
5. Embedding worker generates vectors and writes to Qdrant.
6. Query service retrieves, reranks, grounds answer, and emits citations.

## 8.3 Ingestion entry and document registration

Inputs:
- PDF, JPEG, PNG initially.
- Optional metadata from user: title, document type hint, effective date.

Registration behavior:
- Assign immutable `document_id` and `owner_user_id`.
- Persist `ingestion_status` lifecycle: `queued`, `extracting`, `chunking`, `embedding`, `indexed`, `failed`.
- Store checksum for dedupe and idempotent reprocessing.

Storage posture:
- Originals remain encrypted at rest in private Blob containers.
- No public endpoints; private networking only, per Section 6.

## 8.4 Text extraction, OCR, and normalization

Processing strategy:
- Attempt native text extraction first for digitally generated PDFs.
- Fall back to OCR for scanned PDFs/images via Azure AI Document Intelligence.
- Keep page boundaries and source offsets to support precise citations.

Normalization rules:
- Normalize whitespace and common OCR artifacts.
- Preserve headings, section labels, and numbered clauses where possible.
- Keep a canonical extracted-text artifact versioned by extractor pipeline version.

## 8.5 Classification and routing

Classification is advisory for retrieval quality, not an authorization boundary.

- Classify document into coarse families (HOA, lease, insurance, lab result, other).
- Attach taxonomy tags used by domain prompts (Legal/Health) later.
- Low-confidence classification does not block ingestion; it marks document for possible reclassification.

## 8.6 Chunking strategy

Chunk design for v1:
- Hybrid structural + token chunking.
- Prefer section-based splits when headings/clauses are detected.
- Apply target chunk size of approximately 600-900 tokens with overlap around 80-120 tokens.
- Include metadata on every chunk: `owner_user_id`, `document_id`, `page_start`, `page_end`, `section_label`, `chunk_index`, `source_version`.

Chunking constraints:
- Never mix content from different documents in one chunk.
- Preserve citation traceability to page and clause boundaries.

## 8.7 Embeddings and indexing

Embedding generation:
- Use a single embedding model per environment in v1 to avoid vector-space drift.
- Record `embedding_model_id` and `embedding_version` on each chunk.

Qdrant indexing model:
- Store vectors with payload metadata required for strict owner filtering.
- Mandatory filter on `owner_user_id` for every query path.
- Keep `document_id` and taxonomy fields in payload for post-retrieval filtering and diagnostics.

Re-embedding policy:
- Model upgrade triggers background re-embedding by document batches.
- Old and new vectors should not be mixed in the same query path once cutover begins.

## 8.8 Retrieval and ranking

Query-time flow:
1. Validate caller identity and entitlement.
2. Retrieve candidate chunks with mandatory `owner_user_id` filter.
3. Apply optional spoke/domain filters (Legal or Health taxonomy).
4. Rerank top candidates with a lightweight relevance stage.
5. Build grounded context from top chunks only.

Retrieval guardrails:
- Reject retrieval if ownership filter is absent.
- Ignore instructions embedded in documents that attempt to override system policy.
- Cap max chunks and token budget to contain cost and prompt overflow risk.

## 8.9 Answer grounding and citation generation

Grounding policy:
- Model must answer from retrieved chunks only.
- If evidence is insufficient, return explicit uncertainty and next-step guidance.

Citation format for v1:
- For each claim, include `document title`, `page` (or page range), and `section label` when available.
- Each citation references the exact chunk IDs used to generate that claim.
- Never emit citations to chunks outside the caller's ownership scope.

## 8.10 Failure handling, retries, and idempotency

**Decision (v1): asynchronous, queue-backed ingestion with resumable stages.**

Failure model:
- Each stage writes durable status and error code.
- Retry transient failures with exponential backoff and bounded attempts.
- Route poison jobs to a dead-letter queue for manual review.

Idempotency model:
- Use `document_id` + artifact version as idempotency key per stage.
- Re-running a completed stage with identical inputs must be a no-op.

## 8.11 Security controls specific to RAG

- Enforce ownership filtering in retrieval service and data access layer.
- Restrict Qdrant network access to CanI Docs backend only.
- Redact high-risk secrets from logs and tracing payloads.
- Validate uploaded file type and size before processing.
- Scan uploads for malware before extraction.

## 8.12 Performance and cost targets (v1)

- Ingestion P95 for common documents (<25 pages): under 90 seconds to indexed state.
- Query P95 end-to-end latency: under 5 seconds for standard question lengths.
- Max context assembly budget: bounded token window with deterministic truncation.
- Batch embedding jobs to reduce per-request overhead and smooth spend.

## 8.13 Observability for the pipeline

Required metrics:
- Documents ingested per hour and failure rate by stage.
- Queue depth, retry counts, dead-letter count.
- Extraction quality indicators (OCR confidence bands).
- Retrieval hit quality (top-k score distribution) and citation coverage ratio.

Required logs/traces:
- Correlated trace ID across upload, ingestion workers, retrieval, and answer generation.
- Structured error logs with stage name, document ID, and retry state.

## 8.14 v1 implementation checklist

- Async ingestion queue and worker deployment on AKS.
- Document registration table with status lifecycle and checksums.
- Extraction + OCR pipeline with versioned artifacts.
- Chunking module with deterministic metadata output.
- Embedding worker and Qdrant write path with owner payload fields.
- Retrieval service enforcing mandatory ownership filter and reranking.
- Citation renderer returning page/section-aware references.
- Pipeline metrics, alerts, and dead-letter operations runbook.

## 8.15 Open questions

1. Should Legal and Health share one retrieval service with domain policies, or run separate retrieval services per spoke?
2. What minimum OCR confidence threshold should trigger reprocessing versus user-visible warning?
3. Which reranker model provides acceptable quality/cost at v1 scale?

---

[← Identity & access (CanI Hub)](07-identity-and-access.md) | [Back to index](README.md) | Next: [Data model & storage →](09-data-model-and-storage.md)