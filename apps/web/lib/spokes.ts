// Spoke configuration — the "Extensibility Framework / Token Mapping" from the
// design language (§3, §6). Each spoke swaps a small set of tokens; the master
// layout DOM never changes. Colours are applied as CSS custom properties on the
// shell wrapper; label/icon/placeholder are consumed directly in JSX.

export type SpokeKey = "hub" | "legal" | "health" | "finance";

export interface Spoke {
  key: SpokeKey;
  /** Header label: "CanI | {label}". */
  label: string;
  /** --brand-accent */
  accent: string;
  /** --spoke-badge-success */
  badgeSuccess: string;
  /** Stand-in for --icon-set-domain (a glyph rather than an SVG for the prototype). */
  icon: string;
  /** --input-placeholder */
  placeholder: string;
}

export const SPOKES: Record<SpokeKey, Spoke> = {
  hub: {
    key: "hub",
    label: "Hub",
    accent: "#1E3A5F", // Slate Blue — the Control Plane
    badgeSuccess: "#1E3A5F",
    icon: "◈",
    placeholder: "Ask a question...",
  },
  legal: {
    key: "legal",
    label: "Legal",
    accent: "#4A7C59", // Sage Green
    badgeSuccess: "#4A7C59",
    icon: "§",
    placeholder: "Ask about your contract, lease, or covenants...",
  },
  health: {
    key: "health",
    label: "Health",
    accent: "#D96C5C", // Warm Coral
    badgeSuccess: "#D96C5C",
    icon: "✚",
    placeholder: "Ask about your health record or benefits...",
  },
  finance: {
    key: "finance",
    label: "Finance",
    accent: "#205A5B", // Deep Teal
    badgeSuccess: "#205A5B",
    icon: "₮",
    placeholder: "Upload tax notice or loan agreement...",
  },
};

export const SPOKE_ORDER: SpokeKey[] = ["hub", "legal", "health", "finance"];
