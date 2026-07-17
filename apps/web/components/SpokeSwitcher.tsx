"use client";

import { SPOKES, SPOKE_ORDER, type SpokeKey } from "@/lib/spokes";

interface SpokeSwitcherProps {
  current: SpokeKey;
  onChange: (key: SpokeKey) => void;
}

/**
 * Demonstrates the Extensibility Framework (§6): switching a spoke re-maps the
 * design tokens (accent, badge colour, label, icon, placeholder) with no
 * structural DOM change.
 */
export function SpokeSwitcher({ current, onChange }: SpokeSwitcherProps) {
  return (
    <div className="spoke-switcher" role="group" aria-label="Switch spoke">
      <p className="spoke-switcher__label">Spoke</p>
      <div className="spoke-switcher__options">
        {SPOKE_ORDER.map((key) => {
          const spoke = SPOKES[key];
          const active = current === key;
          return (
            <button
              key={key}
              type="button"
              className={`spoke-chip${active ? " spoke-chip--active" : ""}`}
              style={{ ["--chip-accent" as string]: spoke.accent } as React.CSSProperties}
              onClick={() => onChange(key)}
              aria-pressed={active}
            >
              <span className="spoke-chip__dot" aria-hidden />
              {spoke.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
