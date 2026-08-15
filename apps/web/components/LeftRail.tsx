"use client";

import type { Spoke, SpokeKey } from "@/lib/spokes";
import type { Principal } from "@/lib/backendAuth";
import { getDisplayName } from "@/lib/displayName";
import { SpokeSwitcher } from "./SpokeSwitcher";
import { JurisdictionPicker } from "./JurisdictionPicker";

/** The primary views the rail switches between. */
export type NavView = "workspace" | "upload" | "documents";

interface LeftRailProps {
  spoke: Spoke;
  collapsed: boolean;
  onToggle: () => void;
  onSpokeChange: (key: SpokeKey) => void;
  user: Principal;
  activeView: NavView;
  onNavigate: (view: NavView) => void;
  /** Public-law jurisdiction selection (docs/20 §20.8 Q2) — only shown for the Legal spoke. */
  jurisdiction: string;
  onJurisdictionChange: (slug: string) => void;
}

const NAV_ITEMS: { glyph: string; label: string; view: NavView }[] = [
  { glyph: "\u25EB", label: "Workspace", view: "workspace" },
  { glyph: "\u2191", label: "Upload", view: "upload" },
  { glyph: "\u2751", label: "Documents", view: "documents" },
];

/**
 * Collapsible structural menu (§5): full-width at 25%, collapsing to an
 * icon-only rail. Hosts the domain icon, primary nav, spoke switcher, and the
 * user profile stub.
 */
export function LeftRail({
  spoke,
  collapsed,
  onToggle,
  onSpokeChange,
  user,
  activeView,
  onNavigate,
  jurisdiction,
  onJurisdictionChange,
}: LeftRailProps) {
  const displayName = getDisplayName(user.user_id, user.idp_subject, user.display_name);
  return (
    <nav className={`rail${collapsed ? " rail--collapsed" : ""}`} aria-label="Primary">
      <button
        type="button"
        className="rail__brandbtn"
        onClick={onToggle}
        aria-label={collapsed ? "Expand menu" : "Collapse menu"}
        aria-expanded={!collapsed}
      >
        <span className="rail__domain-icon" aria-hidden>
          {spoke.icon}
        </span>
        {!collapsed && <span className="rail__brand">CanI</span>}
      </button>

      <ul className="rail__nav">
        {NAV_ITEMS.map((item) => (
          <li key={item.label}>
            <button
              type="button"
              className={`rail__item${activeView === item.view ? " rail__item--active" : ""}`}
              onClick={() => onNavigate(item.view)}
              aria-current={activeView === item.view ? "page" : undefined}
              title={collapsed ? item.label : undefined}
            >
              <span className="rail__glyph" aria-hidden>
                {item.glyph}
              </span>
              {!collapsed && <span className="rail__itemlabel">{item.label}</span>}
            </button>
          </li>
        ))}
      </ul>

      <div className="rail__footer">
        {!collapsed && <SpokeSwitcher current={spoke.key} onChange={onSpokeChange} />}
        {!collapsed && spoke.key === "legal" && (
          <JurisdictionPicker value={jurisdiction} onChange={onJurisdictionChange} />
        )}
        <div className="rail__profile" title={user.idp_subject}>
          <span className="rail__avatar" aria-hidden>
            {displayName.charAt(0).toUpperCase() || "◎"}
          </span>
          {!collapsed && (
            <span className="rail__profileinfo">
              <span className="rail__itemlabel">{displayName}</span>
              <a className="rail__signout" href="/auth/logout">
                Sign out
              </a>
            </span>
          )}
        </div>
      </div>
    </nav>
  );
}
