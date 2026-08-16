/** Replicates CSS `object-fit: cover` for manual canvas drawing (canvas has no built-in
 * equivalent) — used to draw LiveAvatar's video frames into the fixed-size avatar tile
 * without distorting the aspect ratio. */

export interface CoverCrop {
  sx: number;
  sy: number;
  sWidth: number;
  sHeight: number;
}

/**
 * Computes the source rectangle to pass to
 * `ctx.drawImage(source, sx, sy, sWidth, sHeight, 0, 0, destWidth, destHeight)` so the
 * result covers the destination exactly, cropping whichever axis overflows.
 */
export function computeCoverCrop(
  sourceWidth: number,
  sourceHeight: number,
  destWidth: number,
  destHeight: number,
): CoverCrop {
  if (sourceWidth <= 0 || sourceHeight <= 0 || destWidth <= 0 || destHeight <= 0) {
    return { sx: 0, sy: 0, sWidth: sourceWidth, sHeight: sourceHeight };
  }

  const sourceRatio = sourceWidth / sourceHeight;
  const destRatio = destWidth / destHeight;

  let sWidth = sourceWidth;
  let sHeight = sourceHeight;
  if (sourceRatio > destRatio) {
    sWidth = sourceHeight * destRatio; // source wider than dest — crop the sides
  } else {
    sHeight = sourceWidth / destRatio; // source taller than dest — crop top/bottom
  }

  return {
    sx: (sourceWidth - sWidth) / 2,
    sy: (sourceHeight - sHeight) / 2,
    sWidth,
    sHeight,
  };
}
