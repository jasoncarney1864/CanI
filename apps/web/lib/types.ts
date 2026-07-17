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
  | "extracting"
  | "chunking"
  | "embedding"
  | "indexed"
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
}

// --- Prototype-only shapes (NOT yet in the backend API) ----------------------
// Inline source-text highlight spans are the one design element the current API
// does not provide. They are modelled here so the UI can render the full
// "Spotlight" experience against mock data; wiring them to real data is deferred
// backend work.

export interface SourceParagraph {
  /** Corresponds to a Citation.chunk_id for highlight matching. */
  id: string;
  text: string;
}

export interface SourceDocument {
  title: string;
  section_label: string;
  paragraphs: SourceParagraph[];
  /** The chunk_id to spotlight in the Document Viewer. */
  highlightChunkId: string;
}
