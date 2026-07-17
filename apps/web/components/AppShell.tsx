"use client";

import { useState } from "react";
import { SPOKES, type SpokeKey } from "@/lib/spokes";
import { mockAnswer, mockDocument } from "@/lib/mockData";
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
  const spoke = SPOKES[spokeKey];

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
          <ConversationPane answer={mockAnswer} spoke={spoke} />
          <DocumentViewer doc={mockDocument} />
        </div>
      </div>
    </div>
  );
}
