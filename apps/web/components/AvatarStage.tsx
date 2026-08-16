"use client";

import { useEffect, useRef } from "react";
import type { AvatarState } from "@/lib/useLiveAvatar";
import { applyChromaKey } from "@/lib/chromaKey";
import { computeCoverCrop } from "@/lib/canvasCover";

interface AvatarStageProps {
  state: AvatarState;
  error: string | null;
  isStreamReady: boolean;
  attach: (element: HTMLMediaElement) => void;
  onToggle: () => void;
}

// Must match .avatar-stage__frame's width/height in globals.css — canvas resolution is
// set explicitly rather than measured, since the frame's size isn't currently dynamic.
const AVATAR_TILE_SIZE_PX = 160;

/**
 * Optional LiveAvatar (HeyGen) video tile — voices the spoken answer with a lip-synced
 * face instead of audio alone. Free tier only (2 min/session, 1 concurrent session,
 * watermarked), so it's opt-in per conversation rather than auto-started; toggling it
 * off (or ending the page) tears the session down via useLiveAvatar's stop().
 *
 * The video element the SDK attaches to is kept off-screen (see .avatar-stage__video-source
 * in globals.css) rather than shown directly: LiveAvatar's studio avatars render against a
 * solid green backdrop baked into the stream itself, with no session/SDK-level way to
 * change it (see lib/chromaKey.ts for what was actually checked). Each frame is instead
 * drawn to a visible canvas with the green keyed out to transparent, so whatever the
 * surrounding page section's own background is shows through naturally instead of
 * hardcoding a matching color here.
 */
export function AvatarStage({ state, error, isStreamReady, attach, onToggle }: AvatarStageProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (isStreamReady && videoRef.current) attach(videoRef.current);
  }, [isStreamReady, attach]);

  // Chroma-key render loop: draws the hidden video's current frame onto the visible
  // canvas every animation frame, keying out the green backdrop as it goes. Runs only
  // once the stream is actually producing frames, and tears down on unmount/stream change.
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!isStreamReady || !video || !canvas) return;

    // willReadFrequently: this loop calls getImageData every frame — opts into the
    // software rendering path Chrome recommends for that access pattern, avoiding
    // per-frame GPU->CPU readback cost.
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return; // canvas 2D unsupported — leave the tile blank rather than crash

    let cancelled = false;
    const draw = () => {
      if (cancelled) return;
      const { videoWidth, videoHeight } = video;
      if (videoWidth > 0 && videoHeight > 0) {
        const { sx, sy, sWidth, sHeight } = computeCoverCrop(
          videoWidth,
          videoHeight,
          canvas.width,
          canvas.height,
        );
        ctx.drawImage(video, sx, sy, sWidth, sHeight, 0, 0, canvas.width, canvas.height);
        const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
        applyChromaKey(frame);
        ctx.putImageData(frame, 0, 0);
      }
      rafRef.current = requestAnimationFrame(draw);
    };
    rafRef.current = requestAnimationFrame(draw);

    return () => {
      cancelled = true;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [isStreamReady]);

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
          <video ref={videoRef} className="avatar-stage__video-source" autoPlay playsInline aria-hidden="true" />
          <canvas
            ref={canvasRef}
            width={AVATAR_TILE_SIZE_PX}
            height={AVATAR_TILE_SIZE_PX}
            className="avatar-stage__canvas"
            role="img"
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
