"use client";

import { useState } from "react";
import { SPOKES, type SpokeKey } from "@/lib/spokes";
import { mockAnswer, mockDocument } from "@/lib/mockData";
import type { RetrievalAnswer } from "@/lib/types";
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
  // Seed with the Oakwood sample so the workspace is populated on first paint;
  // a live query replaces it. `pending` marks the seed vs. a real API result.
  const [answer, setAnswer] = useState<RetrievalAnswer>(mockAnswer);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      setAnswer(data as RetrievalAnswer);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed.");
    } finally {
      setLoading(false);
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
          <DocumentViewer doc={mockDocument} />
        </div>
      </div>
    </div>
  );
}
