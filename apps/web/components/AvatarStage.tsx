"use client";

import { useEffect, useRef } from "react";
import type { AvatarState } from "@/lib/useLiveAvatar";

interface AvatarStageProps {
  state: AvatarState;
  error: string | null;
  isStreamReady: boolean;
  attach: (element: HTMLMediaElement) => void;
  onToggle: () => void;
}

/**
 * Optional LiveAvatar (HeyGen) video tile — voices the spoken answer with a lip-synced
 * face instead of audio alone. Free tier only (2 min/session, 1 concurrent session,
 * watermarked), so it's opt-in per conversation rather than auto-started; toggling it
 * off (or ending the page) tears the session down via useLiveAvatar's stop().
 */
export function AvatarStage({ state, error, isStreamReady, attach, onToggle }: AvatarStageProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (isStreamReady && videoRef.current) attach(videoRef.current);
  }, [isStreamReady, attach]);

  const active = state === "connecting" || state === "connected";

  return (
    <div className="avatar-stage" data-state={state}>
      <button
        type="button"
        className="avatar-stage__toggle"
        onClick={onToggle}
        disabled={state === "connecting"}
        aria-pressed={active}
      >
        {state === "connecting" ? "Connecting…" : active ? "Hide avatar" : "Show talking avatar"}
      </button>

      {active && (
        <div className="avatar-stage__frame">
          <video
            ref={videoRef}
            className="avatar-stage__video"
            autoPlay
            playsInline
            aria-label="LiveAvatar talking avatar"
          />
          {!isStreamReady && <p className="avatar-stage__status">Connecting…</p>}
        </div>
      )}

      {error && (
        <p className="avatar-stage__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
