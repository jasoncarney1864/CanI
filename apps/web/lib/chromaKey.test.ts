import { describe, expect, it } from "vitest";
import { applyChromaKey } from "./chromaKey";

function makeImageData(pixels: Array<[number, number, number, number]>): ImageData {
  const data = new Uint8ClampedArray(pixels.length * 4);
  pixels.forEach(([r, g, b, a], i) => {
    data[i * 4] = r;
    data[i * 4 + 1] = g;
    data[i * 4 + 2] = b;
    data[i * 4 + 3] = a;
  });
  return { data, width: pixels.length, height: 1, colorSpace: "srgb" } as ImageData;
}

describe("applyChromaKey", () => {
  it("keys out a pure studio green pixel to fully transparent", () => {
    const frame = makeImageData([[0, 255, 0, 255]]);
    applyChromaKey(frame);
    expect(frame.data[3]).toBe(0);
  });

  it("leaves a pure red pixel untouched (wrong hue, not green-dominant)", () => {
    const frame = makeImageData([[255, 0, 0, 255]]);
    applyChromaKey(frame);
    expect(frame.data[3]).toBe(255);
  });

  it("leaves a pure blue pixel untouched (hue outside 90-150 range)", () => {
    const frame = makeImageData([[0, 0, 255, 255]]);
    applyChromaKey(frame);
    expect(frame.data[3]).toBe(255);
  });

  it("leaves a skin-tone pixel untouched (not green-dominant at all)", () => {
    const frame = makeImageData([[240, 200, 170, 255]]);
    applyChromaKey(frame);
    expect(frame.data[3]).toBe(255);
  });

  it("leaves a low-saturation near-white-green pixel untouched (below minSaturation)", () => {
    const frame = makeImageData([[250, 255, 250, 255]]);
    applyChromaKey(frame);
    expect(frame.data[3]).toBe(255);
  });

  it("applies a soft (partial) alpha falloff for a mildly green edge pixel rather than a hard cutout", () => {
    // Green-dominant, in hue range, but only weakly so — an edge/fringe pixel.
    const frame = makeImageData([[100, 140, 90, 255]]);
    applyChromaKey(frame);
    expect(frame.data[3]).toBeGreaterThan(0);
    expect(frame.data[3]).toBeLessThan(255);
  });

  it("respects custom options (narrower hue range excludes a pixel the default would key)", () => {
    // Hue ~150.6°, green-dominant — keyed by the default 90-150 range only if inclusive at
    // the boundary; use a value clearly outside a much narrower custom range instead.
    const frame = makeImageData([[0, 255, 60, 255]]); // hue ~132°, within default range
    applyChromaKey(frame, { minHue: 60, maxHue: 100 }); // custom range excludes ~132°
    expect(frame.data[3]).toBe(255);
  });

  it("processes multiple pixels independently in the same frame", () => {
    const frame = makeImageData([
      [0, 255, 0, 255], // green — keyed
      [255, 0, 0, 255], // red — untouched
    ]);
    applyChromaKey(frame);
    expect(frame.data[3]).toBe(0);
    expect(frame.data[7]).toBe(255);
  });
});
