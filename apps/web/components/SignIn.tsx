// Sign-in screen (A2). Shown to unauthenticated visitors instead of the workspace.
// A full-page link to /auth/login (not fetch) so the browser follows hub-api's redirect
// to Entra. Uses the Hub spoke's Slate Blue and the design tokens.

// The guided-tour demo site, where new visitors learn the product and sign up.
// TODO: move to a custom domain and align its branding with CanI when it's rerouted.
const DEMO_SITE_URL = "https://happy-forest-0bce5670f.7.azurestaticapps.net/";

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
