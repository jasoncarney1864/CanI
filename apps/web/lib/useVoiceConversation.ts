"use client";

// Voice-first conversation loop (Gemini-Live-style, not chatbot-style):
//   tap once -> listening -> (you stop talking) -> thinking -> speaking -> listening...
// The session keeps cycling hands-free until explicitly stopped. Uses the Web
// Speech API (SpeechRecognition for capture + endpointing, speechSynthesis for
// the spoken answer). Falls back gracefully where unsupported.

import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceState = "unsupported" | "off" | "listening" | "thinking" | "speaking";

// Minimal structural types for the (still-prefixed) Web Speech API.
interface RecognitionResultChunk {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<RecognitionResultChunk>;
}
interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: RecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  start(): void;
  abort(): void;
}
type RecognitionCtor = new () => RecognitionLike;

function getRecognitionCtor(): RecognitionCtor | undefined {
  if (typeof window === "undefined") return undefined;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

export function useVoiceConversation({ onUtterance }: { onUtterance: (text: string) => void }) {
  const [state, setState] = useState<VoiceState>("off");
  const [transcript, setTranscript] = useState("");
  const recognitionRef = useRef<RecognitionLike | null>(null);
  const activeRef = useRef(false);

  useEffect(() => {
    if (!getRecognitionCtor()) setState("unsupported");
  }, []);

  /** One listen turn: capture speech, auto-submit when the speaker pauses. */
  const listen = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor || !activeRef.current) return;
    const rec = new Ctor();
    recognitionRef.current = rec;
    rec.lang = typeof navigator !== "undefined" ? navigator.language || "en-US" : "en-US";
    rec.interimResults = true;
    rec.continuous = false; // browser endpointing = "you stopped talking"
    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      setTranscript(finalText || interim);
    };
    rec.onend = () => {
      if (!activeRef.current) return;
      const text = finalText.trim();
      if (text) {
        setState("thinking");
        onUtterance(text);
      } else {
        listen(); // silence — keep waiting patiently
      }
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        activeRef.current = false;
        setTranscript("");
        setState("off");
      }
      // other errors (no-speech, aborted, network) fall through to onend
    };
    setTranscript("");
    setState("listening");
    try {
      rec.start();
    } catch {
      /* already started */
    }
  }, [onUtterance]);

  /** Begin a hands-free conversation session (requires a user gesture). */
  const start = useCallback(() => {
    if (!getRecognitionCtor()) return;
    activeRef.current = true;
    if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    listen();
  }, [listen]);

  /** End the session entirely. */
  const stop = useCallback(() => {
    activeRef.current = false;
    recognitionRef.current?.abort();
    if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    setTranscript("");
    setState((s) => (s === "unsupported" ? s : "off"));
  }, []);

  /**
   * Mark that a question was submitted by other means (typed) while a session
   * is active, so the loop pauses listening and waits for the answer.
   */
  const interject = useCallback(() => {
    if (!activeRef.current) return;
    recognitionRef.current?.abort();
    setTranscript("");
    setState("thinking");
  }, []);

  /** Speak the answer aloud, then automatically resume listening. */
  const speak = useCallback(
    (text: string) => {
      if (!activeRef.current) return;
      if (typeof window === "undefined" || !("speechSynthesis" in window)) {
        listen();
        return;
      }
      setState("speaking");
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.04;
      u.onend = () => {
        if (activeRef.current) listen();
      };
      u.onerror = () => {
        if (activeRef.current) listen();
      };
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    },
    [listen],
  );

  // Teardown on unmount.
  useEffect(
    () => () => {
      activeRef.current = false;
      recognitionRef.current?.abort();
      if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    },
    [],
  );

  return { state, transcript, start, stop, speak, interject };
}
