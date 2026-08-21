"use client";

import { useEffect, useState } from "react";
import { SPOKES, type SpokeKey } from "@/lib/spokes";
import type { Principal } from "@/lib/backendAuth";
import type { DocumentText, RetrievalAnswer } from "@/lib/types";
import { getDisplayName } from "@/lib/displayName";
import { DEFAULT_JURISDICTION, getStoredJurisdiction, setStoredJurisdiction } from "@/lib/jurisdictions";
import { buildAnswerMarkdown } from "@/lib/exportAnswer";
import { LeftRail, type NavView } from "./LeftRail";
import { ConversationPane, type SaveAsDocumentState } from "./ConversationPane";
import { DocumentViewer } from "./DocumentViewer";
import { UploadView } from "./UploadView";
import { DocumentsView } from "./DocumentsView";

interface AppShellProps {
  initialSpoke?: SpokeKey;
  user: Principal;
}

// Shared between handleAsk (the query) and saveAnswerAsDocument (docs/21 §3.6) — the
// backend's DocumentSpoke enum uses title-cased names, the frontend's SpokeKey doesn't.
const SPOKE_TO_BACKEND: Record<SpokeKey, string> = {
  hub: "General",
  legal: "Legal",
  health: "Health",
  finance: "Finance",
};

/**
 * The master layout (§5, revised): collapsible left rail + a header + an
 * answer-dominant workspace. The conversation fills the page; the Document
 * Viewer opens as a slide-over only when a citation is clicked.
 *
 * Spoke tokens are injected as CSS custom properties on the wrapper, so a spoke
 * switch re-themes the whole tree without any structural change (§6).
 */
export function AppShell({ initialSpoke = "legal", user }: AppShellProps) {
  const [spokeKey, setSpokeKey] = useState<SpokeKey>(initialSpoke);
  const [view, setView] = useState<NavView>("workspace");
  const [collapsed, setCollapsed] = useState(false);
  const [answer, setAnswer] = useState<RetrievalAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // "Save as document" (docs/21 §3.6): the question is retained separately from the
  // per-turn `error`/`loading` state above because it needs to survive into
  // saveAnswerAsDocument, which runs well after handleAsk's own request has settled.
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveAsDocumentState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  // Document Viewer state: the cited document's source text + which chunks to spotlight.
  const [doc, setDoc] = useState<DocumentText | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [highlightChunkIds, setHighlightChunkIds] = useState<Set<string>>(new Set());
  // Public-law jurisdiction (docs/20 §20.8 Q2): session-level, client-side only. Starts at
  // the default so server and first client render match, then syncs from localStorage
  // once mounted — avoids a hydration mismatch for what's currently a one-state picker.
  const [jurisdiction, setJurisdiction] = useState<string>(DEFAULT_JURISDICTION);
  useEffect(() => {
    setJurisdiction(getStoredJurisdiction());
  }, []);
  function handleJurisdictionChange(slug: string) {
    setJurisdiction(slug);
    setStoredJurisdiction(slug);
  }
  const spoke = SPOKES[spokeKey];

  // Returns the answer so the voice loop can speak it aloud (null on failure).
  async function handleAsk(question: string): Promise<RetrievalAnswer | null> {
    setLastQuestion(question);
    // A new question makes any prior "Saved" status stale — that button/label belongs to
    // the answer it was clicked for, not the one about to replace it.
    setSaveState("idle");
    setSaveError(null);
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          question,
          spoke: SPOKE_TO_BACKEND[spoke.key],
          // Public-law dual-corpus retrieval (docs/20 §20.8): explicit rather than relying
          // on the backend's spoke-based default, and the selected state is sent on every
          // query per Q2 — retrieval-worker only actually uses it when include_public_law
          // resolves true.
          include_public_law: spoke.key === "legal",
          jurisdictions: [jurisdiction],
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.error ?? `Query failed (${res.status}).`);
      }
      const result = data as RetrievalAnswer;
      setAnswer(result);
      // A fresh answer invalidates whatever document the viewer was showing.
      setViewerOpen(false);
      setDoc(null);
      setHighlightChunkIds(new Set());
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed.");
      return null;
    } finally {
      setLoading(false);
    }
  }

  // "Save as document" (docs/21 §3.6): persists the current answer via POST
  // /documents/generated so it flows through the ordinary ingestion pipeline and shows up
  // on the Documents page like any upload.
  async function saveAnswerAsDocument() {
    if (!answer || !lastQuestion) return;
    setSaveState("saving");
    setSaveError(null);
    try {
      const res = await fetch("/api/documents/generated", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title: null,
          spoke: SPOKE_TO_BACKEND[spoke.key],
          markdown: buildAnswerMarkdown(lastQuestion, answer),
          provenance: {
            question: lastQuestion,
            model_id: null,
            citations: answer.citations.map((c) => ({
              chunk_id: c.chunk_id,
              document_id: c.source_kind === "user_document" ? c.document_id : null,
              document_title: c.source_kind === "user_document" ? c.document_title : null,
              citation_ref: c.source_kind === "user_document" ? null : c.citation_ref,
            })),
          },
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.error ?? `Couldn't save (${res.status}).`);
      }
      setSaveState("saved");
    } catch (e) {
      setSaveState("error");
      setSaveError(e instanceof Error ? e.message : "Couldn't save.");
    }
  }

  // Load the source text of one cited document and spotlight every chunk the answer
  // cites within it (§5). Opened on demand when the user clicks a citation card.
  async function showCitedDocument(documentId: string, result: RetrievalAnswer) {
    setViewerOpen(true);
    setHighlightChunkIds(
      new Set(
        result.citations
          .filter((c) => c.document_id === documentId)
          .map((c) => c.chunk_id),
      ),
    );
    setDocLoading(true);
    try {
      const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/text`);
      setDoc(res.ok ? ((await res.json()) as DocumentText) : null);
    } catch {
      setDoc(null);
    } finally {
      setDocLoading(false);
    }
  }

  const shellStyle = {
    ["--brand-accent" as string]: spoke.accent,
    ["--spoke-badge-success" as string]: spoke.badgeSuccess,
  } as React.CSSProperties;

  return (
    <div className="shell" style={shellStyle} data-spoke={spoke.key}>
      <LeftRail
        spoke={spoke}
        collapsed={collapsed}
        onToggle={() => setCollapsed((v) => !v)}
        onSpokeChange={setSpokeKey}
        user={user}
        activeView={view}
        onNavigate={setView}
        jurisdiction={jurisdiction}
        onJurisdictionChange={handleJurisdictionChange}
      />

      <div className="main">
        <header className="topbar">
          <span className="topbar__brand">
            CanI <span className="topbar__divider" aria-hidden>|</span>{" "}
            <span className="topbar__spoke">{spoke.label}</span>
          </span>
          <span className="topbar__auth">
            <span className="topbar__user" title={user.idp_subject}>
              {getDisplayName(user.user_id, user.idp_subject, user.display_name)}
            </span>
            <a className="topbar__signout" href="/auth/logout">
              Sign out
            </a>
          </span>
        </header>

        {view === "workspace" && (
          <div className="workspace">
            <ConversationPane
              answer={answer}
              spoke={spoke}
              loading={loading}
              error={error}
              onAsk={handleAsk}
              activeDocumentId={viewerOpen ? (doc?.document_id ?? null) : null}
              onSelectCitation={(documentId) => {
                if (answer) void showCitedDocument(documentId, answer);
              }}
              onSaveAsDocument={() => void saveAnswerAsDocument()}
              saveState={saveState}
              saveError={saveError}
              onGoToDocuments={() => setView("documents")}
            />
            {viewerOpen && (
              <DocumentViewer
                doc={doc}
                highlightChunkIds={highlightChunkIds}
                loading={docLoading}
                onClose={() => setViewerOpen(false)}
              />
            )}
          </div>
        )}

        {view === "upload" && (
          <div className="panel">
            <UploadView onGoToDocuments={() => setView("documents")} />
          </div>
        )}

        {view === "documents" && (
          <div className="panel">
            <DocumentsView spoke={spoke.key === "hub" ? "General" : spoke.label} />
          </div>
        )}
      </div>
    </div>
  );
}
