import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev harness only — proxies /api to the live marketing API Container App
// by default, so relative fetch("/api/...") calls work without needing
// Cors:AllowedOrigin to include the local dev origin. Override with
// VITE_DEV_API_PROXY_TARGET (shell-exported, e.g. http://localhost:5099)
// to point at a locally-running `dotnet run` instance instead, for
// testing backend changes end-to-end before they're deployed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target:
          process.env.VITE_DEV_API_PROXY_TARGET ??
          "https://ca-sondra-keys-marketing-api.grayflower-56c5dfe2.eastus2.azurecontainerapps.io",
        changeOrigin: true,
      },
    },
  },
});
