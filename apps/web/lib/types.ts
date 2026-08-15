// Types for the CanI web prototype.
//
// The API-facing shapes below intentionally mirror the backend contracts in
// apps/shared-lib/cani_shared/models.py so this prototype can be wired to the
// live docs-api later with minimal churn.

/** Mirrors cani_shared LawSourceKind plus "user_document" — the Citation discriminator
 * (docs/20-public-law-corpus-design.md §20.8). */
export type CitationSourceKind =
  | "user_document"
  | "state_statute"
  | "county_code"
  | "federal_statute"
  | "federal_regulation";

interface CitationBase {
  chunk_id: string;
  /** Verbatim text of the cited chunk. For a law citation this IS the quoted statute
   * text (docs/20 §20.1 principle 1); for a document citation it powers the Document
   * Viewer spotlight. */
  snippet?: string | null;
}

/** A citation into the caller's own uploaded document — unchanged from pre-Phase-2. */
export interface UserDocumentCitation extends CitationBase {
  source_kind: "user_document";
  document_id: string;
  document_title: string;
  page_start: number;
  page_end: number;
  section_label: string | null;
  citation_ref?: null;
  source_url?: null;
  law_fetched_at?: null;
}

/** A citation into the shared public-law corpus (docs/20 §20.8) — no document/page to
 * open, so the client renders citation_ref + verbatim quote + source link + fetched date
 * instead of the Document Viewer button. */
export interface LawCitation extends CitationBase {
  source_kind: Exclude<CitationSourceKind, "user_document">;
  document_id?: null;
  document_title?: null;
  page_start?: null;
  page_end?: null;
  section_label?: null;
  citation_ref: string;
  source_url: string;
  law_fetched_at?: string | null;
}

/** Mirrors cani_shared Citation. Branch on source_kind — see docs/20 §20.11 Phase 3. */
export type Citation = UserDocumentCitation | LawCitation;

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

// --- LiveAvatar (HeyGen) session-token exchange (POST /avatar/session-token) --------

/** Mirrors docs-api's AvatarSessionTokenResponse. Short-lived — the frontend uses it
 * directly with LiveAvatar's own Web SDK to open the WebRTC session; it never reaches
 * this app's server again after the client receives it. */
export interface AvatarSessionToken {
  session_token: string;
}
