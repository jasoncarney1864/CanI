import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";

// Explicit imports (not `test.globals`) means Testing Library's own afterEach-based
// auto-cleanup never registers — do it here instead, or every test after the first in a
// file sees every previous test's DOM still mounted.
afterEach(() => {
  cleanup();
});
