import { describe, expect, it } from "vitest";
import { estimatePcm24kDurationMs } from "./pcmAudio";

describe("estimatePcm24kDurationMs", () => {
  it("returns 0 for an empty string", () => {
    expect(estimatePcm24kDurationMs("")).toBe(0);
  });

  it("estimates 1 second of audio for 48000 bytes (24kHz * 2 bytes/sample)", () => {
    const oneSecondOfSilence = btoa("\x00".repeat(48000));
    expect(estimatePcm24kDurationMs(oneSecondOfSilence)).toBeCloseTo(1000, 0);
  });

  it("estimates half a second of audio for 24000 bytes", () => {
    const halfSecond = btoa("\x00".repeat(24000));
    expect(estimatePcm24kDurationMs(halfSecond)).toBeCloseTo(500, 0);
  });

  it("scales linearly with byte length", () => {
    const twoSeconds = btoa("\x00".repeat(96000));
    expect(estimatePcm24kDurationMs(twoSeconds)).toBeCloseTo(2000, 0);
  });
});
