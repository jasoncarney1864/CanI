"use client";

import { SUPPORTED_STATES } from "@/lib/jurisdictions";

interface JurisdictionPickerProps {
  value: string;
  onChange: (slug: string) => void;
}

/**
 * "Select your state" store-picker (à la Walmart/Best Buy) for the Legal spoke's public-law
 * corpus (docs/20 §20.8 Q2, decided). Ships with exactly one option — with a single
 * supported state the picker is effectively informative rather than a choice, which is
 * fine: it sets the UX contract now so adding states later is a SUPPORTED_STATES row, not
 * a redesign.
 */
export function JurisdictionPicker({ value, onChange }: JurisdictionPickerProps) {
  return (
    <div className="jurisdiction-picker">
      <label htmlFor="jurisdiction-select" className="jurisdiction-picker__label">
        State
      </label>
      <select
        id="jurisdiction-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="jurisdiction-picker__select"
      >
        {SUPPORTED_STATES.map((state) => (
          <option key={state.slug} value={state.slug}>
            {state.name}
          </option>
        ))}
      </select>
    </div>
  );
}
