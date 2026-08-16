/**
 * Real-time green-screen removal for LiveAvatar's video stream.
 *
 * HeyGen's "studio" avatars bake a solid green background directly into the stream's
 * pixels — there's no session-start parameter or SDK method to change it (checked: neither
 * FULL nor LITE mode's create-session-token request body has any background field, and
 * HeyGen's own demo app just renders the raw stream over a plain black div). HeyGen
 * documents this exact canvas-based technique as the supported client-side fix
 * (docs.liveavatar.com/docs/guides/change-background): per-frame HSV thresholding with a
 * soft alpha falloff at the edges to avoid a hard-cutout halo.
 *
 * Defaults use the docs' own *narrowed* hue range (their default is 60-180°, narrowed to
 * 90-150° "if the avatar's clothing is being partially keyed out") — picked as the safer
 * starting point since this was written without a live avatar feed to visually tune
 * against. If real footage shows green fringing at the edges, widen back toward 60-180;
 * if clothing or skin gets clipped, narrow further.
 */

export interface ChromaKeyOptions {
  minHue?: number;
  maxHue?: number;
  minSaturation?: number;
  /** How strongly green must dominate red/blue for a pixel to be gated as background at
   * all. HeyGen's guide calls this the green-dominance "threshold" (their default 1.0,
   * meaning green just needs to be the largest channel). */
  threshold?: number;
  /** Multiplier on the greenness score for the soft-edge alpha falloff within the gated
   * region — HeyGen's guide calls out this exact knob ("greenness * 4") for halo
   * mitigation; higher values key out fringe pixels more aggressively. */
  edgeSoftness?: number;
}

export const DEFAULT_CHROMA_KEY_OPTIONS: Required<ChromaKeyOptions> = {
  minHue: 90,
  maxHue: 150,
  minSaturation: 0.1,
  threshold: 1.0,
  edgeSoftness: 4,
};

/** RGB (0-255 each) to hue (degrees, 0-360) and saturation (0-1). Value is unused here. */
function rgbToHueSaturation(r: number, g: number, b: number): [hue: number, saturation: number] {
  const rN = r / 255;
  const gN = g / 255;
  const bN = b / 255;
  const max = Math.max(rN, gN, bN);
  const min = Math.min(rN, gN, bN);
  const delta = max - min;

  let hue = 0;
  if (delta !== 0) {
    if (max === rN) hue = ((gN - bN) / delta) % 6;
    else if (max === gN) hue = (bN - rN) / delta + 2;
    else hue = (rN - gN) / delta + 4;
    hue *= 60;
    if (hue < 0) hue += 360;
  }
  const saturation = max === 0 ? 0 : delta / max;
  return [hue, saturation];
}

/**
 * Mutates `imageData.data`'s alpha channel in place, keying out green-screen pixels.
 * Pixels outside the hue/saturation/dominance gate are left untouched; pixels inside it
 * get a soft alpha reduction proportional to how strongly green they are, rather than a
 * hard 0/255 cutout.
 */
export function applyChromaKey(imageData: ImageData, options: ChromaKeyOptions = {}): void {
  const { minHue, maxHue, minSaturation, threshold, edgeSoftness } = {
    ...DEFAULT_CHROMA_KEY_OPTIONS,
    ...options,
  };
  const data = imageData.data;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];

    const maxRB = Math.max(r, b);
    if (g <= maxRB * threshold) continue; // not green-dominant enough to be background

    const [hue, saturation] = rgbToHueSaturation(r, g, b);
    if (hue < minHue || hue > maxHue || saturation < minSaturation) continue;

    const greenness = (g - maxRB) / 255; // 0..1
    const alphaScale = Math.max(0, 1 - greenness * edgeSoftness);
    data[i + 3] = Math.round(data[i + 3] * alphaScale);
  }
}
