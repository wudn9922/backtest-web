import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";

// Execute the production TypeScript helper without a browser or new runtime dependency.
const source = fs.readFileSync(new URL("../lib/threshold-segments.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { thresholdSegments, HISTORICAL_THRESHOLD_OPTIONS, resetAfterClose } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`,
);
const row = (date, value, key = "break_day_low") => ({ timestamp: `${date}T04:00:00+00:00`, [key]: value });

test("active BreakDayLow retains its historical line, including single-bar episodes", () => {
  assert.deepEqual(thresholdSegments([row("2024-05-02", 81.11462711525115), row("2024-05-03", 81.11462711525115)], "break_day_low"), [[
    { time: "2024-05-02", value: 81.11462711525115 }, { time: "2024-05-03", value: 81.11462711525115 },
  ]]);
  assert.equal(thresholdSegments([row("2024-05-03", 81)], "break_day_low")[0].length, 1);
  assert.equal(HISTORICAL_THRESHOLD_OPTIONS.pointMarkersVisible, true);
});

test("position-32 May 3 reset leaves May 6 and May 7 inactive without forward fill", () => {
  const rows = [row("2024-05-03", 81.11462711525115), row("2024-05-06", null), row("2024-05-07", null)];
  const before = structuredClone(rows);
  assert.deepEqual(thresholdSegments(rows, "break_day_low"), [[{ time: "2024-05-03", value: 81.11462711525115 }]]);
  assert.deepEqual(rows, before);
  assert.equal(HISTORICAL_THRESHOLD_OPTIONS.priceLineVisible, false);
  assert.equal(HISTORICAL_THRESHOLD_OPTIONS.lastValueVisible, false);
});

test("null bars split episodes instead of connecting the old threshold to a new one", () => {
  const segments = thresholdSegments([row("2024-05-03", 81), row("2024-05-06", null), row("2024-05-07", 84)], "break_day_low");
  assert.deepEqual(segments, [[{ time: "2024-05-03", value: 81 }], [{ time: "2024-05-07", value: 84 }]]);
});

test("position-32 adjacent reset and new break episode do not connect across close", () => {
  const rows = [row("2024-04-30", 83.24296857442113), row("2024-05-01", 81.11462711525115)];
  assert.equal(thresholdSegments(rows, "break_day_low", new Set(["2024-04-30"])).length, 2);
});

test("all threshold kinds obey null/inactive data and share no-current-price options", () => {
  for (const key of ["break_day_low", "protective_stop", "simple_ma_exit_stop", "ma_half_stop", "bias_extreme_threshold_price", "atr_extreme_threshold_price", "first_tp_price", "day1_stop"]) {
    assert.deepEqual(thresholdSegments([row("2024-05-03", null, key)], key), []);
    assert.equal(thresholdSegments([row("2024-05-03", 81, key), row("2024-05-06", null, key)], key)[0].length, 1);
  }
});

test("reset annotations use backend CLOSE events only, without changing audit/execution payloads", () => {
  const event = { source_event: "BREAK_PROTECTION_RESET", metadata: { phase: "CLOSE" }, shares_before: 324, shares_remaining: 324 };
  const events = [event]; const before = structuredClone(events);
  assert.equal(resetAfterClose(events), true);
  assert.equal(resetAfterClose([{ ...event, metadata: { phase: "OPEN" } }]), false);
  assert.equal(resetAfterClose([{ ...event, metadata: {} }]), false);
  assert.deepEqual(events, before);
  const chart = fs.readFileSync(new URL("../components/Charts.tsx", import.meta.url), "utf8");
  assert.match(chart, /\.\.\.HISTORICAL_THRESHOLD_OPTIONS/);
  assert.match(chart, /thresholdSegments\(rows, key, boundaries\)/);
  assert.match(chart, /addThreshold\("simple_ma_exit_stop"/);
  assert.match(chart, /addThreshold\("ma_half_stop"/);
  assert.doesNotMatch(chart, /rows\.filter\(row => row\[key\] != null\)/);
  const inspector = fs.readFileSync(new URL("../components/PositionInspector.tsx", import.meta.url), "utf8");
  assert.match(inspector, /BreakDayLow active intraday · Reset after close/);
});
