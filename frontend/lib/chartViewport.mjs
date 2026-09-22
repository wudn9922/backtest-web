/** Deterministic controls used by the MA_BOX chart. */
export function zoomIn(value) {
  return Math.min(3, Number((Number(value) + 0.25).toFixed(2)));
}

export function zoomOut(value) {
  return Math.max(1, Number((Number(value) - 0.25).toFixed(2)));
}

export function resetZoom() {
  return 1;
}

export function focusWindow(length, start, end, before = 20, after = 10) {
  const last = Math.max(0, Number(length) - 1);
  if (start == null) return { start: 0, end: last };
  const first = Math.max(0, Number(start));
  return {
    start: Math.max(0, first - before),
    end: Math.min(last, (end == null ? first : Number(end)) + after),
  };
}

/**
 * Move a visible index range horizontally while preserving its width. The
 * chart component uses this pure helper for its scroll/pan state transition;
 * clamping is deterministic so a gesture cannot reveal an invalid range.
 */
export function panViewport(range, delta, bounds) {
  const min = Number(bounds?.min ?? 0);
  const max = Math.max(min, Number(bounds?.max ?? range.to));
  const from = Number(range?.from ?? min);
  const to = Math.max(from, Number(range?.to ?? from));
  const width = Math.max(0, to - from);
  let nextFrom = from + Number(delta || 0);
  nextFrom = Math.max(min, Math.min(nextFrom, max - width));
  return { from: nextFrom, to: nextFrom + width };
}
