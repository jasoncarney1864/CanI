"use client";

// Wraps the LiveAvatar (HeyGen) Web SDK (docs-api's POST /avatar/session-token — see
// docs_api_app/liveavatar.py). Lite integration mode: docs-api never touches an LLM here,
// it only mints a short-lived session token; this hook uses that token to open the WebRTC
// session directly with LiveAvatar and feeds it pre-generated answer text via repeat().
//
// The SDK (and its livekit-client dependency) is dynamically imported only once the user
// opts in — free tier is 2 min/session, 1 concurrent session, 10 credits total, so nothing
// here should touch LiveAvatar until start() is actually called.

import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveAvatarSession as LiveAvatarSessionType } from "@heygen/liveavatar-web-sdk";

export type AvatarState = "inactive" | "connecting" | "connected" | "error";

type LiveAvatarModule = typeof import("@heygen/liveavatar-web-sdk");

export function useLiveAvatar() {
  const [state, setState] = useState<AvatarState>("inactive");
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef<LiveAvatarSessionType | null>(null);
  const moduleRef = useRef<LiveAvatarModule | null>(null);
  const activeRef = useRef(false);

  const stop = useCallback(async () => {
    activeRef.current = false;
    const session = sessionRef.current;
    sessionRef.current = null;
    setIsStreamReady(false);
    setState("inactive");
    if (session) {
      try {
        await session.stop();
      } catch {
        /* already gone */
      }
    }
  }, []);

  const start = useCallback(async () => {
    if (sessionRef.current) return; // already active — free tier is 1 concurrent session
    setError(null);
    setState("connecting");
    try {
      const tokenRes = await fetch("/api/avatar/session-token", { method: "POST" });
      if (tokenRes.status === 503) {
        setState("error");
        setError("The talking avatar isn't set up on this deployment.");
        return;
      }
      if (!tokenRes.ok) throw new Error(`session-token request failed (${tokenRes.status})`);
      const { session_token: sessionToken } = (await tokenRes.json()) as { session_token: string };

      const mod = moduleRef.current ?? (await import("@heygen/liveavatar-web-sdk"));
      moduleRef.current = mod;
      const session = new mod.LiveAvatarSession(sessionToken);
      activeRef.current = true;
      sessionRef.current = session;

      session.on(mod.SessionEvent.SESSION_STREAM_READY, () => setIsStreamReady(true));
      session.on(mod.SessionEvent.SESSION_DISCONNECTED, () => {
        // Free-tier sessions hard-cap at 2 minutes — this also fires when LiveAvatar
        // ends the session server-side, not just in response to our own stop().
        if (!activeRef.current) return;
        activeRef.current = false;
        sessionRef.current = null;
        setIsStreamReady(false);
        setState("inactive");
      });

      await session.start();
      setState("connected");
    } catch (e) {
      console.error("LiveAvatar session failed to start:", e);
      activeRef.current = false;
      sessionRef.current = null;
      setState("error");
      setError("Couldn't start the talking avatar. Try again, or keep going without it.");
    }
  }, []);

  const attach = useCallback((element: HTMLMediaElement) => {
    sessionRef.current?.attach(element);
  }, []);

  /** Make the avatar speak pre-generated text (Lite mode: we already have the answer,
   * LiveAvatar only voices + lip-syncs it), resolving once it finishes speaking. */
  const speak = useCallback(
    (text: string): Promise<void> => {
      const session = sessionRef.current;
      const mod = moduleRef.current;
      if (!session || !mod || state !== "connected") return Promise.resolve();

      return new Promise((resolve) => {
        const onEnded = () => {
          session.off(mod.AgentEventsEnum.AVATAR_SPEAK_ENDED, onEnded);
          resolve();
        };
        session.on(mod.AgentEventsEnum.AVATAR_SPEAK_ENDED, onEnded);
        try {
          session.repeat(text);
        } catch (e) {
          console.error("LiveAvatar repeat() failed:", e);
          session.off(mod.AgentEventsEnum.AVATAR_SPEAK_ENDED, onEnded);
          resolve();
        }
      });
    },
    [state],
  );

  // Teardown on unmount — never leave a session running past the 1-concurrency limit.
  useEffect(
    () => () => {
      void stop();
    },
    [stop],
  );

  return { state, isStreamReady, error, start, stop, attach, speak };
}
