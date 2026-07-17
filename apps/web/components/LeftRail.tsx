"use client";

import type { Spoke, SpokeKey } from "@/lib/spokes";
import { SpokeSwitcher } from "./SpokeSwitcher";

interface LeftRailProps {
  spoke: Spoke;
  collapsed: boolean;
  onToggle: () => void;
  onSpokeChange: (key: SpokeKey) => void;
}

const NAV_ITEMS = [
  { glyph: "\u25EB", label: "Workspace", active: true },
  { glyph: "\u2191", label: "Upload", active: false },
  { glyph: "\u2751", label: "Documents", active: false },
];

/**
 * Collapsible structural menu (§5): full-width at 25%, collapsing to an
 * icon-only rail. Hosts the domain icon, primary nav, spoke switcher, and the
 * user profile stub.
 */
export function LeftRail({ spoke, collapsed, onToggle, onSpokeChange }: LeftRailProps) {
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
          <li
            key={item.label}
            className={`rail__item${item.active ? " rail__item--active" : ""}`}
          >
            <span className="rail__glyph" aria-hidden>
              {item.glyph}
            </span>
            {!collapsed && <span className="rail__itemlabel">{item.label}</span>}
          </li>
        ))}
      </ul>

      <div className="rail__footer">
        {!collapsed && <SpokeSwitcher current={spoke.key} onChange={onSpokeChange} />}
        <div className="rail__profile">
          <span className="rail__avatar" aria-hidden>
            &#9678;
          </span>
          {!collapsed && <span className="rail__itemlabel">User Profile</span>}
        </div>
      </div>
    </nav>
  );
}
