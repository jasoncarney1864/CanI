import { describe, expect, it } from "vitest";
import { computeCoverCrop } from "./canvasCover";

describe("computeCoverCrop", () => {
  it("returns the full source unmodified when it already matches the destination ratio", () => {
    const crop = computeCoverCrop(160, 160, 160, 160);
    expect(crop).toEqual({ sx: 0, sy: 0, sWidth: 160, sHeight: 160 });
  });

  it("crops the sides when the source is wider than the destination (landscape video into a square tile)", () => {
    const crop = computeCoverCrop(1280, 720, 160, 160);
    // Cropped width should match the source height (1:1 dest ratio), centered horizontally.
    expect(crop.sHeight).toBe(720);
    expect(crop.sWidth).toBe(720);
    expect(crop.sy).toBe(0);
    expect(crop.sx).toBeCloseTo((1280 - 720) / 2);
  });

  it("crops top/bottom when the source is taller than the destination (portrait video into a square tile)", () => {
    const crop = computeCoverCrop(720, 1280, 160, 160);
    expect(crop.sWidth).toBe(720);
    expect(crop.sHeight).toBe(720);
    expect(crop.sx).toBe(0);
    expect(crop.sy).toBeCloseTo((1280 - 720) / 2);
  });

  it("handles a non-square destination correctly", () => {
    const crop = computeCoverCrop(1000, 1000, 200, 100); // dest is 2:1
    expect(crop.sWidth).toBe(1000);
    expect(crop.sHeight).toBe(500);
    expect(crop.sy).toBeCloseTo(250);
  });

  it("falls back to the raw source dimensions when given a zero/negative size", () => {
    const crop = computeCoverCrop(0, 0, 160, 160);
    expect(crop).toEqual({ sx: 0, sy: 0, sWidth: 0, sHeight: 0 });
  });
});
