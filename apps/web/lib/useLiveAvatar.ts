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
import { estimatePcm24kDurationMs } from "./pcmAudio";

export type AvatarState = "inactive" | "connecting" | "connected" | "error";

type LiveAvatarModule = typeof import("@heygen/liveavatar-web-sdk");

// AVATAR_SPEAK_ENDED isn't a documented-reliable event for repeatAudio()-fed speech (see
// speak()'s comment) — this bounds how long a speak() call waits for it before giving up
// on its own, sized off the audio's real duration rather than a blind guess.
const SPEAK_TIMEOUT_SAFETY_MARGIN_MS = 1500;
const SPEAK_TIMEOUT_MIN_MS = 3000;

export function useLiveAvatar() {
  const [state, setState] = useState<AvatarState>("inactive");
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef<LiveAvatarSessionType | null>(null);
  const moduleRef = useRef<LiveAvatarModule | null>(null);
  const activeRef = useRef(false);
  // The currently in-flight speak() call's settle function, if any — lets interrupt()
  // unstick it immediately instead of waiting on (or trusting) a server event.
  const pendingSpeakSettleRef = useRef<(() => void) | null>(null);

  const stop = useCallback(async () => {
    activeRef.current = false;
    const session = sessionRef.current;
    sessionRef.current = null;
    setIsStreamReady(false);
    setIsSpeaking(false);
    pendingSpeakSettleRef.current = null;
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
        setIsSpeaking(false);
        pendingSpeakSettleRef.current = null;
        setState("inactive");
      });
      // Ambient "is the avatar currently talking" state, independent of any specific
      // speak() call's own completion tracking below — drives AvatarStage's interrupt
      // button, which should only show up while there's actually something to interrupt.
      session.on(mod.AgentEventsEnum.AVATAR_SPEAK_STARTED, () => setIsSpeaking(true));
      session.on(mod.AgentEventsEnum.AVATAR_SPEAK_ENDED, () => setIsSpeaking(false));

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
   * LiveAvatar only lip-syncs it), resolving once it finishes speaking (or once the
   * timeout safety net below gives up waiting).
   *
   * repeat()/message() (hand LiveAvatar text, let its own server-side TTS speak it) only
   * work in FULL-mode sessions — the SDK throws "Not permitted in LITE mode" for them,
   * confirmed in its own source. docs-api always mints LITE-mode tokens (liveavatar.py),
   * so LITE's bring-your-own-LLM model turns out to also mean bring-your-own-TTS: we
   * synthesize the audio ourselves via /api/speech (Azure Speech, requesting its
   * raw-24khz-16bit-mono-pcm format) and hand LiveAvatar the finished audio through
   * repeatAudio(), which has no such mode restriction. Confirmed against HeyGen's own
   * demo app (heygen-com/live-avatar-js-sdk, useAvatarActions.ts) — same pattern there.
   *
   * repeatAudio() itself is synchronous/fire-and-forget (its type signature returns
   * `string`, not a Promise) and HeyGen's own demo never waits for AVATAR_SPEAK_ENDED
   * after calling it either — there's no documented guarantee that event reliably fires
   * for audio-fed speech the way it plausibly does for server-side text-to-speech in FULL
   * mode. Without a fallback, a single missed event would hang this promise forever, and
   * with it useVoiceConversation's whole listen->speak->listen loop (its .finally(listen)
   * never runs). The setTimeout below is that fallback. */
  const speak = useCallback(
    (text: string): Promise<void> => {
      const session = sessionRef.current;
      const mod = moduleRef.current;
      if (!session || !mod || state !== "connected") return Promise.resolve();

      return new Promise((resolve) => {
        let settled = false;
        let timeoutId: ReturnType<typeof setTimeout> | null = null;

        const settle = () => {
          if (settled) return;
          settled = true;
          session.off(mod.AgentEventsEnum.AVATAR_SPEAK_ENDED, onEnded);
          if (timeoutId !== null) clearTimeout(timeoutId);
          if (pendingSpeakSettleRef.current === settle) pendingSpeakSettleRef.current = null;
          resolve();
        };

        const onEnded = () => settle();
        session.on(mod.AgentEventsEnum.AVATAR_SPEAK_ENDED, onEnded);
        pendingSpeakSettleRef.current = settle;

        fetch("/api/speech", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, format: "pcm24k" }),
        })
          .then((res) => {
            if (!res.ok) throw new Error(`speech synthesis failed (${res.status})`);
            return res.json() as Promise<{ audio: string }>;
          })
          .then(({ audio }) => {
            session.repeatAudio(audio);
            const timeoutMs = Math.max(
              estimatePcm24kDurationMs(audio) + SPEAK_TIMEOUT_SAFETY_MARGIN_MS,
              SPEAK_TIMEOUT_MIN_MS,
            );
            timeoutId = setTimeout(settle, timeoutMs);
          })
          .catch((e) => {
            console.error("LiveAvatar repeatAudio() failed:", e);
            settle();
          });
      });
    },
    [state],
  );

  /** Stop the avatar's current speech immediately without ending the session — distinct
   * from stop(), which tears the whole WebRTC connection down. session.interrupt() sends
   * `agent.interrupt`, one of the few LiveAvatarSession commands NOT blocked in LITE mode
   * (checked the SDK's own command-gating switch: only AVATAR_SPEAK_TEXT/
   * AVATAR_SPEAK_RESPONSE throw "Not permitted in LITE mode" — AVATAR_INTERRUPT isn't
   * among them), and HeyGen's own demo exposes an "Interrupt" button in every session mode
   * including LITE, so this is supported, documented-by-example behavior, not a workaround.
   * Force-resolves any in-flight speak() immediately rather than waiting on whatever
   * (possibly-absent) event follows an interrupt server-side — same reasoning as the
   * timeout fallback in speak() itself. */
  const interrupt = useCallback(() => {
    const session = sessionRef.current;
    if (!session) return;
    try {
      session.interrupt();
    } catch (e) {
      console.error("LiveAvatar interrupt() failed:", e);
    }
    setIsSpeaking(false);
    pendingSpeakSettleRef.current?.();
  }, []);

  // Teardown on unmount — never leave a session running past the 1-concurrency limit.
  useEffect(
    () => () => {
      void stop();
    },
    [stop],
  );

  return { state, isStreamReady, isSpeaking, error, start, stop, attach, speak, interrupt };
}
