// Types for the CanI web prototype.
//
// The API-facing shapes below intentionally mirror the backend contracts in
// apps/shared-lib/cani_shared/models.py so this prototype can be wired to the
// live docs-api later with minimal churn.

/** Mirrors cani_shared Citation. */
export interface Citation {
  document_id: string;
  document_title: string;
  page_start: number;
  page_end: number;
  section_label: string;
  chunk_id: string;
  /** Verbatim text of the cited chunk (from docs-api). Powers the source snippet + spotlight. */
  snippet?: string | null;
}

/** Mirrors cani_shared VerdictKind. */
export type VerdictKind = "yes" | "yes_with_conditions" | "no" | "insufficient";

/** Mirrors cani_shared Verdict. Present only for yes/no permissibility questions. */
export interface Verdict {
  kind: VerdictKind;
  label: string;
}

/** Mirrors cani_shared RetrievalAnswer (POST /query response). */
export interface RetrievalAnswer {
  answer: string;
  citations: Citation[];
  insufficient_evidence: boolean;
  verdict?: Verdict | null;
}

/** Mirrors cani_shared Document.current_status. */
export type DocumentStatus =
  | "queued"
  | "unpacking"
  | "extracting"
  | "chunking"
  | "embedding"
  | "indexed"
  | "unpacked"
  | "failed";

/** Mirrors cani_shared Document. */
export interface DocumentMeta {
  document_id: string;
  owner_user_id: string;
  title: string;
  source_type: string;
  current_status: DocumentStatus;
  checksum: string;
  created_at: string;
  updated_at: string;
  spoke: string;
}

// --- Document Viewer source text (GET /documents/{id}/text) -------------------
// Real backend shapes now (Sprint 3 A1/B). The viewer renders the document's
// ordered chunks and spotlights the ones whose chunk_id matches a citation.

/** Mirrors cani_shared DocumentChunk. */
export interface DocumentChunk {
  chunk_id: string;
  text: string;
  page_start: number;
  page_end: number;
  section_label: string | null;
  chunk_index: number;
}

/** Mirrors cani_shared DocumentText. */
export interface DocumentText {
  document_id: string;
  title: string;
  chunks: DocumentChunk[];
}
