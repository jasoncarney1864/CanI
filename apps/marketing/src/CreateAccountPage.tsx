import { useEffect, useState, type FormEvent } from "react";
import { Turnstile } from "./Turnstile.tsx";

// Same pattern as DemoRequestForm.tsx's API_ENDPOINT.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

type PageState =
  | "checking_token"
  | "invalid_token"
  | "ready"
  | "submitting"
  | "success"
  | "error";

const GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again.";
const INVALID_TOKEN_MESSAGE = "This invite link is invalid or has expired.";
const MIN_PASSWORD_LENGTH = 12;
const PASSWORD_REQUIREMENTS_MESSAGE =
  `Password must be at least ${MIN_PASSWORD_LENGTH} characters and include an uppercase letter, ` +
  "a lowercase letter, and a special character.";

function getTokenFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("token");
}

// Mirrors PasswordPolicy.cs server-side — this is only a UX nicety, the
// API re-validates independently since a client check can't be trusted.
function isPasswordValid(password: string): boolean {
  return (
    password.length >= MIN_PASSWORD_LENGTH &&
    /[A-Z]/.test(password) &&
    /[a-z]/.test(password) &&
    /[^A-Za-z0-9]/.test(password)
  );
}

export function CreateAccountPage() {
  const [token] = useState(getTokenFromUrl);
  const [email, setEmail] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [captchaResetKey, setCaptchaResetKey] = useState(0);
  const [state, setState] = useState<PageState>("checking_token");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setState("invalid_token");
      return;
    }

    let cancelled = false;

    async function checkToken(currentToken: string) {
      try {
        const response = await fetch(`${API_BASE}/api/account-invites/${encodeURIComponent(currentToken)}`);
        if (cancelled) {
          return;
        }

        if (!response.ok) {
          setState("invalid_token");
          return;
        }

        const body = (await response.json()) as { email: string };
        setEmail(body.email);
        setState("ready");
      } catch {
        if (!cancelled) {
          setState("invalid_token");
        }
      }
    }

    void checkToken(token);
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!isPasswordValid(password)) {
      setErrorMessage(PASSWORD_REQUIREMENTS_MESSAGE);
      setState("error");
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage("Passwords do not match.");
      setState("error");
      return;
    }

    setState("submitting");
    setErrorMessage("");

    try {
      const response = await fetch(`${API_BASE}/api/account-invites/${encodeURIComponent(token!)}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, captchaToken }),
      });

      if (!response.ok) {
        setState("error");
        setErrorMessage(GENERIC_ERROR_MESSAGE);
        setCaptchaToken(null);
        setCaptchaResetKey((key) => key + 1);
        return;
      }

      setState("success");
    } catch {
      setState("error");
      setErrorMessage(GENERIC_ERROR_MESSAGE);
      setCaptchaToken(null);
      setCaptchaResetKey((key) => key + 1);
    }
  }

  if (state === "checking_token") {
    return (
      <main className="section-inner create-account-page">
        <p>Checking your invite link…</p>
      </main>
    );
  }

  if (state === "invalid_token") {
    return (
      <main className="section-inner create-account-page">
        <h1>Invite link invalid</h1>
        <p>{INVALID_TOKEN_MESSAGE}</p>
      </main>
    );
  }

  if (state === "success") {
    return (
      <main className="section-inner create-account-page">
        <h1>Account created</h1>
        <p className="demo-form-status demo-form-status--success" role="status">
          Your account is ready. You can now sign in.
        </p>
      </main>
    );
  }

  return (
    <main className="section-inner create-account-page">
      <h1>Create your account</h1>
      <p>
        Creating an account for <strong>{email}</strong>.
      </p>

      <form className="demo-form" onSubmit={handleSubmit} noValidate>
        <div className="demo-form-field">
          <label htmlFor="create-account-password">Password</label>
          <input
            id="create-account-password"
            name="password"
            type="password"
            required
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <p className="demo-form-hint">{PASSWORD_REQUIREMENTS_MESSAGE}</p>
        </div>

        <div className="demo-form-field">
          <label htmlFor="create-account-confirm-password">Confirm password</label>
          <input
            id="create-account-confirm-password"
            name="confirmPassword"
            type="password"
            required
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
        </div>

        <Turnstile key={captchaResetKey} onToken={setCaptchaToken} />

        {state === "error" && (
          <p className="demo-form-status demo-form-status--error" role="alert">
            {errorMessage}
          </p>
        )}

        <button
          className="button button--primary"
          type="submit"
          disabled={state === "submitting" || (Boolean(import.meta.env.VITE_TURNSTILE_SITE_KEY) && !captchaToken)}
        >
          {state === "submitting" ? "Creating account…" : "Create account"}
        </button>
      </form>
    </main>
  );
}
