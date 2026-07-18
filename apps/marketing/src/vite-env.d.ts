/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Origin the API is hosted on, e.g. https://ca-sondra-keys-marketing-api...
  // Leave unset in development — the Vite dev server proxies /api instead
  // (see vite.config.ts). Set at build time for production, since a static
  // production deployment has no dev-server proxy to rely on.
  readonly VITE_API_BASE_URL?: string;

  // Cloudflare Turnstile site key (public, not a secret). Unset ->
  // Turnstile renders nothing and the backend's CAPTCHA check fails,
  // which is a safe (if unhelpful) default for an environment that
  // hasn't been given a real key yet.
  readonly VITE_TURNSTILE_SITE_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
