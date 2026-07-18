import { useEffect, useId, useRef } from "react";

// The api.js script tag (index.html) attaches this global once loaded.
declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: TurnstileRenderOptions) => string;
      remove: (widgetId: string) => void;
    };
  }
}

interface TurnstileRenderOptions {
  sitekey: string;
  callback: (token: string) => void;
  "expired-callback"?: () => void;
  "error-callback"?: () => void;
}

interface TurnstileProps {
  onToken: (token: string | null) => void;
}

// Renders a Cloudflare Turnstile CAPTCHA widget. Uses the explicit
// render API (window.turnstile.render) rather than the script's
// auto-render data attributes, since auto-render doesn't cooperate with
// React re-mounting this component.
export function Turnstile({ onToken }: TurnstileProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  const domId = useId();
  const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY;

  useEffect(() => {
    if (!siteKey || !containerRef.current) {
      return;
    }

    let cancelled = false;

    function render() {
      if (cancelled || !window.turnstile || !containerRef.current) {
        return;
      }
      widgetIdRef.current = window.turnstile.render(containerRef.current, {
        sitekey: siteKey!,
        callback: (token) => onToken(token),
        "expired-callback": () => onToken(null),
        "error-callback": () => onToken(null),
      });
    }

    if (window.turnstile) {
      render();
    } else {
      // The script tag in index.html may still be loading — poll briefly
      // rather than coordinating load order between index.html and React.
      const interval = setInterval(() => {
        if (window.turnstile) {
          clearInterval(interval);
          render();
        }
      }, 100);
      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }

    return () => {
      cancelled = true;
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
      }
    };
  }, [siteKey, onToken]);

  if (!siteKey) {
    return null;
  }

  return <div ref={containerRef} id={`turnstile-${domId}`} />;
}
