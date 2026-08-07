"use client";

import { useState } from "react";
import { SPOKES, type SpokeKey } from "@/lib/spokes";
import type { Principal } from "@/lib/backendAuth";
import type { DocumentText, RetrievalAnswer } from "@/lib/types";
import { getDisplayName } from "@/lib/displayName";
import { LeftRail, type NavView } from "./LeftRail";
import { ConversationPane } from "./ConversationPane";
import { DocumentViewer } from "./DocumentViewer";
import { UploadView } from "./UploadView";
import { DocumentsView } from "./DocumentsView";

interface AppShellProps {
  initialSpoke?: SpokeKey;
  user: Principal;
}

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
  // Document Viewer state: the cited document's source text + which chunks to spotlight.
  const [doc, setDoc] = useState<DocumentText | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [highlightChunkIds, setHighlightChunkIds] = useState<Set<string>>(new Set());
  const spoke = SPOKES[spokeKey];

  // Returns the answer so the voice loop can speak it aloud (null on failure).
  async function handleAsk(question: string): Promise<RetrievalAnswer | null> {
    setLoading(true);
    setError(null);
    try {
      // Map spoke key to title-cased spoke name for backend
      const spokeMap: Record<SpokeKey, string> = {
        hub: "General",
        legal: "Legal",
        health: "Health",
        finance: "Finance",
      };
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, spoke: spokeMap[spoke.key] }),
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
