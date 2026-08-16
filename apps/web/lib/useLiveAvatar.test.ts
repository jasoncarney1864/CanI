import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLiveAvatar } from "./useLiveAvatar";

// Minimal EventEmitter + fake LiveAvatarSession so the hook's session.on/off/emit calls
// work against something real, without pulling in the actual SDK (which needs a live
// WebRTC/WebSocket backend we don't have in a unit test). Defined inside vi.hoisted since
// vi.mock's factory (below) needs it, and vi.mock itself gets hoisted above imports.
const { FakeLiveAvatarSession, createdSessions } = vi.hoisted(() => {
  const createdSessions: any[] = [];
  class FakeEventEmitterInner {
    private listeners = new Map<string, Array<(...args: unknown[]) => void>>();
    on(event: string, cb: (...args: unknown[]) => void) {
      const list = this.listeners.get(event) ?? [];
      list.push(cb);
      this.listeners.set(event, list);
    }
    off(event: string, cb: (...args: unknown[]) => void) {
      this.listeners.set(event, (this.listeners.get(event) ?? []).filter((l) => l !== cb));
    }
    emit(event: string, ...args: unknown[]) {
      for (const cb of this.listeners.get(event) ?? []) cb(...args);
    }
  }
  class FakeLiveAvatarSession extends FakeEventEmitterInner {
    start = vi.fn().mockResolvedValue(undefined);
    stop = vi.fn().mockResolvedValue(undefined);
    attach = vi.fn();
    repeatAudio = vi.fn();
    interrupt = vi.fn();
    constructor(public token: string) {
      super();
      createdSessions.push(this);
    }
  }
  return { FakeLiveAvatarSession, createdSessions };
});

vi.mock("@heygen/liveavatar-web-sdk", () => ({
  LiveAvatarSession: FakeLiveAvatarSession,
  SessionEvent: { SESSION_STREAM_READY: "stream_ready", SESSION_DISCONNECTED: "disconnected" },
  AgentEventsEnum: { AVATAR_SPEAK_STARTED: "speak_started", AVATAR_SPEAK_ENDED: "speak_ended" },
}));

function mockFetchSequence() {
  global.fetch = vi.fn(async (url: string | URL | Request) => {
    const href = typeof url === "string" ? url : url.toString();
    if (href.includes("/api/avatar/session-token")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ session_token: "fake-session-token" }),
      } as Response;
    }
    if (href.includes("/api/speech")) {
      // Short audio so SPEAK_TIMEOUT_MIN_MS (3000ms) is what actually governs the
      // fallback timeout, keeping the expected value simple and deterministic.
      const shortSilence = btoa("\x00".repeat(4800)); // ~100ms of PCM24k
      return {
        ok: true,
        status: 200,
        json: async () => ({ audio: shortSilence }),
      } as Response;
    }
    throw new Error(`Unexpected fetch URL in test: ${href}`);
  }) as unknown as typeof fetch;
}

async function startedSession() {
  const hook = renderHook(() => useLiveAvatar());
  await act(async () => {
    await hook.result.current.start();
  });
  const session = createdSessions[createdSessions.length - 1];
  return { hook, session };
}

describe("useLiveAvatar", () => {
  beforeEach(() => {
    createdSessions.length = 0;
    mockFetchSequence();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("resolves speak() when AVATAR_SPEAK_ENDED fires normally", async () => {
    const { hook, session } = await startedSession();

    let resolved = false;
    let speakPromise: Promise<void>;
    await act(async () => {
      speakPromise = hook.result.current.speak("hello").then(() => {
        resolved = true;
      });
      await Promise.resolve(); // let the /api/speech fetch + .then chain settle
      await Promise.resolve();
    });

    expect(resolved).toBe(false); // hasn't fired yet
    expect(session.repeatAudio).toHaveBeenCalledTimes(1);

    await act(async () => {
      session.emit("speak_ended");
      await speakPromise;
    });

    expect(resolved).toBe(true);
  });

  it("falls back to the timeout when AVATAR_SPEAK_ENDED never fires", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { hook, session } = await startedSession();

    let resolved = false;
    await act(async () => {
      void hook.result.current.speak("hello").then(() => {
        resolved = true;
      });
      await vi.advanceTimersByTimeAsync(0); // let the fetch microtasks resolve
    });

    expect(resolved).toBe(false);
    expect(session.repeatAudio).toHaveBeenCalledTimes(1);

    // SPEAK_TIMEOUT_MIN_MS floor (3000ms) governs for this short audio — advance just
    // past it without ever emitting speak_ended.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3001);
    });

    expect(resolved).toBe(true);
  });

  it("does not double-resolve if AVATAR_SPEAK_ENDED fires after the timeout already settled", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { hook, session } = await startedSession();

    const spy = vi.fn();
    await act(async () => {
      void hook.result.current.speak("hello").then(spy);
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3001);
    });
    expect(spy).toHaveBeenCalledTimes(1);

    // A late/stray event after the timeout already settled must not blow up or
    // double-fire the resolution.
    await act(async () => {
      session.emit("speak_ended");
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("interrupt() calls session.interrupt() and immediately unsticks a pending speak()", async () => {
    const { hook, session } = await startedSession();

    let resolved = false;
    await act(async () => {
      void hook.result.current.speak("hello").then(() => {
        resolved = true;
      });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(resolved).toBe(false);

    await act(async () => {
      hook.result.current.interrupt();
      await Promise.resolve();
    });

    expect(session.interrupt).toHaveBeenCalledTimes(1);
    expect(resolved).toBe(true);
  });

  it("tracks isSpeaking via AVATAR_SPEAK_STARTED/ENDED", async () => {
    const { hook, session } = await startedSession();
    expect(hook.result.current.isSpeaking).toBe(false);

    act(() => {
      session.emit("speak_started");
    });
    expect(hook.result.current.isSpeaking).toBe(true);

    act(() => {
      session.emit("speak_ended");
    });
    expect(hook.result.current.isSpeaking).toBe(false);
  });

  it("interrupt() sets isSpeaking false immediately, without waiting for an event", async () => {
    const { hook, session } = await startedSession();

    act(() => {
      session.emit("speak_started");
    });
    expect(hook.result.current.isSpeaking).toBe(true);

    act(() => {
      hook.result.current.interrupt();
    });
    expect(hook.result.current.isSpeaking).toBe(false);
  });

  it("interrupt() is a no-op (does not throw) when there's no active session", () => {
    const hook = renderHook(() => useLiveAvatar());
    expect(() => hook.result.current.interrupt()).not.toThrow();
  });
});
