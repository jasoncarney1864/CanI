import { useState, type CSSProperties, type FormEvent } from "react";
import { Turnstile } from "./Turnstile.tsx";

// Relative path in development (the Vite dev server proxies /api — see
// vite.config.ts); VITE_API_BASE_URL prefixes it in production, where the
// built site is served from a different origin than the API.
const API_ENDPOINT = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/demo-requests`;

type SubmitState = "idle" | "submitting" | "success" | "rate_limited" | "error";

const RATE_LIMIT_MESSAGE = "Too many requests. Please try again in a few minutes.";
const GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again.";

// Visually and programmatically hidden, but NOT display:none — some spam
// bots specifically skip display:none/visibility:hidden fields but still
// fill fields positioned off-screen. Combined with aria-hidden + tabIndex,
// this keeps the field invisible to sighted users, screen readers, and
// keyboard navigation alike, while remaining attractive to bots.
const honeypotWrapperStyle: CSSProperties = {
  position: "absolute",
  left: "-9999px",
  width: "1px",
  height: "1px",
  overflow: "hidden",
};

export function DemoRequestForm() {
  const [email, setEmail] = useState("");
  const [mobile, setMobile] = useState("");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState(""); // honeypot — must stay empty
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  // Turnstile tokens are single-use — bumping this remounts the widget
  // (via its key prop below) to get a fresh one after a failed attempt.
  const [captchaResetKey, setCaptchaResetKey] = useState(0);
  const [state, setState] = useState<SubmitState>("idle");
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState("submitting");
    setErrorMessage("");

    try {
      const response = await fetch(API_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, mobile, message, website, captchaToken }),
      });

      if (response.status === 429) {
        setState("rate_limited");
        setErrorMessage(RATE_LIMIT_MESSAGE);
        setCaptchaToken(null);
        setCaptchaResetKey((key) => key + 1);
        return;
      }

      if (!response.ok) {
        setState("error");
        setErrorMessage(GENERIC_ERROR_MESSAGE);
        setCaptchaToken(null);
        setCaptchaResetKey((key) => key + 1);
        return;
      }

      setState("success");
      setEmail("");
      setMobile("");
      setMessage("");
    } catch {
      setState("error");
      setErrorMessage(GENERIC_ERROR_MESSAGE);
      setCaptchaToken(null);
      setCaptchaResetKey((key) => key + 1);
    }
  }

  if (state === "success") {
    return (
      <p className="demo-form-status demo-form-status--success" role="status">
        Thanks — we'll be in touch shortly.
      </p>
    );
  }

  return (
    <form className="demo-form" onSubmit={handleSubmit} noValidate>
      <div className="demo-form-field">
        <label htmlFor="demo-email">Work email</label>
        <input
          id="demo-email"
          name="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>

      <div className="demo-form-field">
        <label htmlFor="demo-mobile">Mobile (optional)</label>
        <input
          id="demo-mobile"
          name="mobile"
          type="tel"
          autoComplete="tel"
          value={mobile}
          onChange={(event) => setMobile(event.target.value)}
        />
      </div>

      <div className="demo-form-field">
        <label htmlFor="demo-message">What would you like to research? (optional)</label>
        <textarea
          id="demo-message"
          name="message"
          rows={4}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
      </div>

      {/* Honeypot field. Intentionally unlabeled: aria-hidden removes it
          from the accessibility tree entirely, and tabIndex={-1} removes it
          from keyboard tab order, so a label would serve no one. */}
      <div style={honeypotWrapperStyle} aria-hidden="true">
        <input
          type="text"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(event) => setWebsite(event.target.value)}
        />
      </div>

      <Turnstile key={captchaResetKey} onToken={setCaptchaToken} />

      {(state === "rate_limited" || state === "error") && (
        <p className="demo-form-status demo-form-status--error" role="alert">
          {errorMessage}
        </p>
      )}

      <button
        className="button button--primary"
        type="submit"
        disabled={state === "submitting" || (Boolean(import.meta.env.VITE_TURNSTILE_SITE_KEY) && !captchaToken)}
      >
        {state === "submitting" ? "Sending…" : "Request a Demo"}
      </button>
    </form>
  );
}
