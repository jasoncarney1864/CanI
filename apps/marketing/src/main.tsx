import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
// Self-hosted, not Google Fonts: the CSP in staticwebapp.config.json only allows fonts
// from the site's own origin, and the product app uses this same pairing.
import "@fontsource-variable/dm-sans";
import "@fontsource-variable/source-serif-4";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
