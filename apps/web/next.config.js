/** @type {import('next').NextConfig} */

// Content-Security-Policy tuned for this Next.js 14 App Router app (C3).
// - 'unsafe-inline' on script/style is required because Next injects inline hydration
//   bootstrap scripts and inline styles (and the app sets a few inline style props for the
//   spoke tokens) without nonces. Tightening to nonce-based CSP is a tracked follow-up.
// - connect-src 'self': the browser only ever calls this app's own /api/* proxies; the
//   backend (hub-api/docs-api) is never reached directly from the client.
// - frame-ancestors 'none' + X-Frame-Options: DENY: no framing (clickjacking).
const CSP = [
  "default-src 'self'",
  "base-uri 'self'",
  "font-src 'self'",
  "img-src 'self' data:",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "connect-src 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
].join("; ");

// Standard security headers applied to every response at the app layer (portable — they
// survive ingress changes and don't depend on NGINX snippet permissions).
const SECURITY_HEADERS = [
  // HSTS: 2 years, include subdomains, preload-eligible. The app is HTTPS-only behind the
  // ingress; this tells browsers to never attempt http for canido.co.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Allow the microphone on same-origin (the voice feature needs it); deny camera/geolocation.
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
  { key: "Content-Security-Policy", value: CSP },
];

const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (.next/standalone) so the container image is a
  // minimal `node server.js` with only the deps it actually uses — no full node_modules.
  output: "standalone",
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

module.exports = nextConfig;
