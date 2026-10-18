// Small helpers for hand-drawn SVG charts (rail, epi curve, trend). Draw at the container's real pixel width.

/** A linear scale: linear([0, 1], [0, 300])(0.5) → 150. */
export function linear([d0, d1], [r0, r1]) {
  const span = d1 - d0 || 1;
  return (value) => r0 + ((value - d0) / span) * (r1 - r0);
}

/** One decimal for SVG attributes, so markup stays short. */
export const px = (n) => Math.round(n * 10) / 10;

/**
 * Calls draw(width) now and whenever el changes width. Returns a stop function.
 * Charts redraw at their real width instead of scaling text.
 */
export function onWidth(el, draw) {
  let last = -1;
  const observer = new ResizeObserver(([entry]) => {
    const width = Math.round(entry.contentRect.width);
    if (width > 0 && width !== last) {
      last = width;
      draw(width);
    }
  });
  observer.observe(el);
  return () => observer.disconnect();
}
