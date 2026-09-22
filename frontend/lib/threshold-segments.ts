import type { Time } from "lightweight-charts";
import type { AuditEvent } from "./types";

// These series describe historical validity, not a current executable price.
export const HISTORICAL_THRESHOLD_OPTIONS = Object.freeze({
  priceLineVisible: false,
  lastValueVisible: false,
  crosshairMarkerVisible: true,
  pointMarkersVisible: true,
});

export function resetAfterClose(events: ReadonlyArray<AuditEvent>): boolean {
  return events.some(event => event.source_event === "BREAK_PROTECTION_RESET"
    && event.metadata.phase === "CLOSE");
}

export function thresholdSegments(
  rows: ReadonlyArray<Record<string, number | string | null>>,
  key: string,
  breakAfterDates: ReadonlySet<string> = new Set(),
): Array<Array<{ time: Time; value: number }>> {
  const segments: Array<Array<{ time: Time; value: number }>> = [];
  let segment: Array<{ time: Time; value: number }> = [];
  const finish = () => {
    if (segment.length) segments.push(segment);
    segment = [];
  };
  for (const row of rows) {
    const date = String(row.timestamp).slice(0, 10);
    const value = row[key];
    if (value == null || !Number.isFinite(Number(value))) {
      finish(); // Never forward-fill, interpolate, or bridge an inactive bar.
    } else {
      segment.push({ time: date as Time, value: Number(value) });
    }
    // A new episode may start on the very next bar, with no null bar between.
    // Keep the reset day's intraday history but never join the two episodes.
    if (breakAfterDates.has(date)) finish();
  }
  finish();
  return segments;
}
