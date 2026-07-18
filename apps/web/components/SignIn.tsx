// Sign-in screen (A2). Shown to unauthenticated visitors instead of the workspace.
// A full-page link to /auth/login (not fetch) so the browser follows hub-api's redirect
// to Entra. Uses the Hub spoke's Slate Blue and the design tokens.

// The guided-tour demo site, where new visitors learn the product and sign up.
// TODO(cutover): canido.co DNS must point at the marketing site, and the Cloudflare
// Turnstile widget's allowed hostnames need canido.co + www.canido.co added.
const DEMO_SITE_URL = "https://canido.co/";

export function SignIn() {
  return (
    <main
      className="signin"
      style={{
        ["--brand-accent" as string]: "#1e3a5f",
        ["--spoke-badge-success" as string]: "#1e3a5f",
      }}
    >
      <div className="signin__card">
        <div className="signin__brand">
          CanI<span className="signin__dot">.</span>
        </div>
        <p className="signin__tagline">
          Ask your documents. Get grounded, cited answers you can trust.
        </p>
        <a className="signin__button" href="/auth/login">
          Sign in
        </a>
        <p className="signin__signup">
          New here?{" "}
          <a className="signin__signup-link" href={DEMO_SITE_URL}>
            Take the tour &amp; sign up
          </a>
        </p>
        <p className="signin__note">Secured by Microsoft Entra.</p>
      </div>
    </main>
  );
}
