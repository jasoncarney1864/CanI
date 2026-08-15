import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Minimal Vitest setup for component/unit tests (no existing test framework in apps/web
// before docs/20 Phase 3) — jsdom environment, the same "@/" alias tsconfig.json defines,
// and jest-dom matchers via setupFiles.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: false,
  },
});
