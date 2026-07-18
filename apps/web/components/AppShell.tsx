"use client";

import { useState } from "react";
import { SPOKES, type SpokeKey } from "@/lib/spokes";
import type { DocumentText, RetrievalAnswer } from "@/lib/types";
import { LeftRail } from "./LeftRail";
import { ConversationPane } from "./ConversationPane";
import { DocumentViewer } from "./DocumentViewer";

interface AppShellProps {
  initialSpoke?: SpokeKey;
}

/**
 * The master "Spotlight" layout (§5): collapsible left rail + a header + a
 * dual-pane workspace (Conversation 35% / Document Viewer 65%).
 *
 * Spoke tokens are injected as CSS custom properties on the wrapper, so a spoke
 * switch re-themes the whole tree without any structural change (§6).
 */
export function AppShell({ initialSpoke = "legal" }: AppShellProps) {
  const [spokeKey, setSpokeKey] = useState<SpokeKey>(initialSpoke);
  const [collapsed, setCollapsed] = useState(false);
  const [answer, setAnswer] = useState<RetrievalAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Document Viewer state: the cited document's source text + which chunks to spotlight.
  const [doc, setDoc] = useState<DocumentText | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [highlightChunkIds, setHighlightChunkIds] = useState<Set<string>>(new Set());
  const spoke = SPOKES[spokeKey];

  async function handleAsk(question: string) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.error ?? `Query failed (${res.status}).`);
      }
      const result = data as RetrievalAnswer;
      setAnswer(result);
      void loadCitedDocument(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed.");
    } finally {
      setLoading(false);
    }
  }

  // Load the source text of the first cited document and spotlight every chunk cited
  // within it (§5). One answer can cite several documents; the viewer shows the first.
  async function loadCitedDocument(result: RetrievalAnswer) {
    const first = result.citations[0];
    if (!first) {
      setDoc(null);
      setHighlightChunkIds(new Set());
      return;
    }
    setHighlightChunkIds(
      new Set(
        result.citations
          .filter((c) => c.document_id === first.document_id)
          .map((c) => c.chunk_id),
      ),
    );
    setDocLoading(true);
    try {
      const res = await fetch(`/api/documents/${encodeURIComponent(first.document_id)}/text`);
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
      />

      <div className="main">
        <header className="topbar">
          <span className="topbar__brand">
            CanI <span className="topbar__divider" aria-hidden>|</span>{" "}
            <span className="topbar__spoke">{spoke.label}</span>
          </span>
          <span className="topbar__auth">[ User Profile / Auth ]</span>
        </header>

        <div className="workspace">
          <ConversationPane
            answer={answer}
            spoke={spoke}
            loading={loading}
            error={error}
            onAsk={handleAsk}
          />
          <DocumentViewer doc={doc} highlightChunkIds={highlightChunkIds} loading={docLoading} />
        </div>
      </div>
    </div>
  );
}
