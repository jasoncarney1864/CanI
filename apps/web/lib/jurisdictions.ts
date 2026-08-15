// Jurisdiction selection for the public-law corpus (docs/20-public-law-corpus-design.md
// §20.8 Q2, decided): a "select your state" store-picker pattern, session-level and
// client-side only via localStorage — no hub-api profile field in v1. Renders from a
// multi-state-capable list that ships with exactly one entry (Nevada); adding a state
// later is a SUPPORTED_STATES row, not a redesign.

export interface StateOption {
  /** Jurisdiction slug sent as-is in RetrieveRequest.jurisdictions. */
  slug: string;
  name: string;
}

export const SUPPORTED_STATES: StateOption[] = [{ slug: "us-nv", name: "Nevada" }];

export const DEFAULT_JURISDICTION: string = SUPPORTED_STATES[0].slug;

const STORAGE_KEY = "cani.jurisdiction";

/** Reads the stored jurisdiction, falling back to the default on the server, when
 * localStorage is unavailable (e.g. private browsing), or when the stored value no
 * longer names a supported state. */
export function getStoredJurisdiction(): string {
  if (typeof window === "undefined") return DEFAULT_JURISDICTION;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && SUPPORTED_STATES.some((s) => s.slug === stored)) return stored;
  } catch {
    // localStorage can throw (private browsing, disabled storage) — fall back silently.
  }
  return DEFAULT_JURISDICTION;
}

export function setStoredJurisdiction(slug: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, slug);
  } catch {
    // Best-effort persistence; a failed write just means the picker resets next visit.
  }
}
