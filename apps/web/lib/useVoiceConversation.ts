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
  // A user-visible reason the last voice attempt couldn't run (mic blocked/busy, no speech
  // backend — e.g. Edge exposes the API but doesn't transcribe). Null when voice is healthy.
  const [error, setError] = useState<string | null>(null);
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
      // no-speech (silence) and aborted (our own stop/interject) are benign: fall through
      // to onend, which keeps waiting patiently. Everything else means voice can't run —
      // stop the loop and tell the user why, instead of silently re-listening forever.
      if (e.error === "no-speech" || e.error === "aborted") return;
      activeRef.current = false;
      setTranscript("");
      setState("off");
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        setError("Microphone access is blocked. Allow the mic for this site, then tap to try again.");
      } else if (e.error === "audio-capture") {
        setError("No microphone found, or another app is using it. Free the mic, then tap to try again.");
      } else if (e.error === "network") {
        // Chromium exposes SpeechRecognition but only Chrome ships a working speech backend;
        // Edge fails here with `network`. See memory: voice-web-speech-edge-limitation.
        setError("Voice couldn't reach the speech service — this browser may not support it. Try Chrome, or type your question below.");
      } else {
        setError("Voice input stopped unexpectedly. Tap to try again, or type your question below.");
      }
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
    setError(null); // clear any prior failure message on a fresh attempt
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

  /** Fallback: use browser speechSynthesis when Azure Speech is unavailable. */
  const speakWithBrowser = useCallback(
    (text: string) => {
      if (!activeRef.current) return;
      if (typeof window === "undefined" || !("speechSynthesis" in window)) {
        listen();
        return;
      }
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

  /** Speak the answer aloud, then automatically resume listening. */
  const speak = useCallback(
    (text: string) => {
      if (!activeRef.current) return;

      // Try Azure Speech first, fall back to browser speechSynthesis if unavailable
      setState("speaking");

      // Attempt to use Azure AI Speech neural TTS
      fetch("/api/speech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })
        .then(async (response) => {
          if (response.status === 501) {
            // Azure Speech not configured - fall back to browser
            throw new Error("Azure Speech not configured");
          }
          if (!response.ok) {
            throw new Error(`Speech API failed: ${response.status}`);
          }
          return response.arrayBuffer();
        })
        .then((audioData) => {
          // Play the audio using Web Audio API
          if (!activeRef.current) return;
          
          const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
          audioContext.decodeAudioData(audioData, (buffer) => {
            if (!activeRef.current) return;
            
            const source = audioContext.createBufferSource();
            source.buffer = buffer;
            source.connect(audioContext.destination);
            source.onended = () => {
              if (activeRef.current) listen();
            };
            source.start(0);
          }, (error) => {
            console.error("Audio decode error:", error);
            // Fall back to browser speech on decode error
            speakWithBrowser(text);
          });
        })
        .catch((error) => {
          // Fall back to browser speechSynthesis
          console.log("Using browser speech fallback:", error.message);
          speakWithBrowser(text);
        });
    },
    [listen, speakWithBrowser],
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

  return { state, transcript, error, start, stop, speak, interject };
}
