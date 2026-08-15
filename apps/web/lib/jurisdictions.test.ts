import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_JURISDICTION,
  SUPPORTED_STATES,
  getStoredJurisdiction,
  setStoredJurisdiction,
} from "./jurisdictions";

describe("jurisdictions (docs/20 §20.8 Q2 — session-level, client-side only)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("ships with exactly one supported state, Nevada", () => {
    expect(SUPPORTED_STATES).toEqual([{ slug: "us-nv", name: "Nevada" }]);
    expect(DEFAULT_JURISDICTION).toBe("us-nv");
  });

  it("falls back to the default when nothing is stored", () => {
    expect(getStoredJurisdiction()).toBe(DEFAULT_JURISDICTION);
  });

  it("round-trips a stored, supported jurisdiction", () => {
    setStoredJurisdiction("us-nv");
    expect(getStoredJurisdiction()).toBe("us-nv");
    expect(window.localStorage.getItem("cani.jurisdiction")).toBe("us-nv");
  });

  it("falls back to the default when the stored value names an unsupported state", () => {
    window.localStorage.setItem("cani.jurisdiction", "us-ca");
    expect(getStoredJurisdiction()).toBe(DEFAULT_JURISDICTION);
  });
});
