/** @type {import('next').NextConfig} */

// Content-Security-Policy tuned for this Next.js 14 App Router app (C3).
// - 'unsafe-inline' on script/style is required because Next injects inline hydration
//   bootstrap scripts and inline styles (and the app sets a few inline style props for the
//   spoke tokens) without nonces. Tightening to nonce-based CSP is a tracked follow-up.
// - connect-src 'self': the browser only ever calls this app's own /api/* proxies; the
//   backend (hub-api/docs-api) is never reached directly from the client. EXCEPTION:
//   LiveAvatar (useLiveAvatar.ts) deliberately opens a direct browser->vendor WebRTC/WS
//   session using the token docs-api mints — that traffic never touches our origin, so it
//   needs explicit connect-src entries rather than going through 'self'.
//   - api.liveavatar.com: SDK's REST calls (SessionApiClient, const.js API_URL) and,
//     as far as we've confirmed, the same host serves the session-event WebSocket
//     (LiveAvatarSession.js connectWebSocket) — unconfirmed by live traffic yet, watch
//     devtools on next test in case ws_url turns out to be a different host.
//   - *.livekit.cloud / *.livekit.run (wss + https): the LiveKit-hosted WebRTC signaling
//     room (room.connect() in LiveAvatarSession.js) plus its own region-discovery fetch
//     (GET https://<host>/settings/regions, confirmed by live traffic 2026-08-16 — the
//     wss-only version we shipped first missed this plain-HTTPS call). Domain pattern
//     inferred from livekit-client's own bundled isCloud() hostname check
//     (node_modules/@heygen/liveavatar-web-sdk/lib/index.esm.js: `serverUrl.hostname
//     .endsWith('.livekit.cloud') || serverUrl.hostname.endsWith('.livekit.run')`).
//   - webrtc-signaling.heygen.io: HeyGen's own WebRTC signaling host (confirmed by live
//     traffic 2026-08-16, session path /v2-alpha/interactive-avatar/session/<id>). Not
//     referenced anywhere in the SDK's static source — it's the ws_url returned
//     dynamically per-session — so this is the exact confirmed host, not a *.heygen.io
//     wildcard; broaden only if devtools shows a different heygen.io subdomain.
// - frame-ancestors 'none' + X-Frame-Options: DENY: no framing (clickjacking).
const CSP = [
  "default-src 'self'",
  "base-uri 'self'",
  "font-src 'self'",
  "img-src 'self' data:",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "connect-src 'self' https://api.liveavatar.com wss://api.liveavatar.com https://*.livekit.cloud wss://*.livekit.cloud https://*.livekit.run wss://*.livekit.run wss://webrtc-signaling.heygen.io",
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
