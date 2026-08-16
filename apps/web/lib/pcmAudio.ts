/** Helpers for the raw 16-bit/24kHz/mono PCM audio LiveAvatar's repeatAudio() expects
 * (see useLiveAvatar.ts's speak() for why — Lite-mode sessions can't use repeat()/message()). */

const PCM24K_BYTES_PER_SECOND = 24000 * 2; // 24kHz * 2 bytes/sample (16-bit mono)

/** Estimated playback duration, in milliseconds, of a base64-encoded PCM16/24kHz/mono
 * audio string — used to size a timeout fallback rather than guessing a fixed number,
 * since we know the exact byte length before ever sending the audio. */
export function estimatePcm24kDurationMs(base64Audio: string): number {
  if (!base64Audio) return 0;
  const byteLength = atob(base64Audio).length;
  return (byteLength / PCM24K_BYTES_PER_SECOND) * 1000;
}
