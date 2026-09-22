import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  buildAnalyticsBoundaryPath,
  buildAnalyticsDay2Marker,
  buildAnalyticsStopPath,
  MA_ANALYTICS_DAY2_STATUS_LABELS,
  MA_ANALYTICS_OBSERVATION_ORIGINS,
  MA_ANALYTICS_TARGET_TYPES,
  MA_ANALYTICS_TERMINAL_LABELS,
  prepareMaAnalyticsChart,
} from "../lib/maAnalyticsChart.mjs";

test("analytics chart presents backend bars and selected event overlays unchanged", () => {
  const bars = [{ date: "2021-01-01", sma: 100, long_day1_threshold: 100.2, event_ids: ["e1"] }];
  const chart = {
    daily_data: bars,
    events: [{ event_id: "e1", d1_date: "2021-01-01" }, { event_id: "e2", d1_date: "2021-01-02" }],
    failures: [{ event_id: "e1", terminal_outcome: "SIDEWAYS", sideways_window_dates: ["2021-01-04"] }],
    target_outcomes: [
      { event_id: "e1", target_type: "PCT_3", condition_type: "BREAKOUT", observation_origin: "POST_D1", target_level: 103 },
      { event_id: "e2", target_type: "PCT_3", condition_type: "BREAKOUT", observation_origin: "POST_D1", target_level: 104 },
    ],
    target_session_audit: [
      { event_id: "e1", target_type: "PCT_3", condition_type: "BREAKOUT", observation_origin: "POST_D1", date: "2021-01-02", stop_level: 98.5 },
      { event_id: "e1", target_type: "ATR_1", condition_type: "BREAKOUT", observation_origin: "POST_D1", date: "2021-01-02", stop_level: 98 },
    ],
  };
  const model = prepareMaAnalyticsChart(chart, "e1");
  assert.equal(model.bars, bars);
  assert.equal(model.selectedEvent.event_id, "e1");
  assert.equal(model.targets.length, 1);
  assert.equal(model.targets[0].target_level, 103);
  assert.equal(model.stopAudit.length, 1);
  assert.equal(model.stopAudit[0].stop_level, 98.5);
  assert.equal(model.failure.terminal_outcome, "SIDEWAYS");
});

test("chart overlay uses selected backend target, origin, stop, reference, retest, and box values verbatim", () => {
  const event = {
    event_id: "e1", d1_date: "2021-01-01", direction: "LONG", reference_entry: 111.123,
    volume_evaluable: true, volume_change: 0.27, vol_ge_10: true, vol_ge_20: true, vol_ge_30: false,
    entanglement_cohort: "ENTANGLED_AT_SIGNAL", entanglement_box_id: "box-1",
  };
  const bar = {
    date: "2021-01-03", open: 100, high: 104, low: 99, close: 102, sma: 97,
    box_active_at_session_start: true, box_id_at_session_start: "box-1",
    box_high_at_session_start: 109.876, box_low_at_session_start: 88.765,
    box_formed_on_close: false, box_active_after_close: true, event_ids: [],
  };
  const targetRows = MA_ANALYTICS_TARGET_TYPES.map((targetType, index) => ({
    event_id: "e1", target_type: targetType, condition_type: "DAY2_SUCCESS_AND_VOL_GE_20",
    observation_origin: "POST_D2_SUCCESS", target_level: 237.891 + index * 11.117,
    observation_start_date: "2021-01-04", resolution_date: "2021-01-06",
  }));
  const auditRows = MA_ANALYTICS_TARGET_TYPES.map((targetType, index) => ({
    event_id: "e1", target_type: targetType, condition_type: "DAY2_SUCCESS_AND_VOL_GE_20",
    observation_origin: "POST_D2_SUCCESS", date: "2021-01-04", stop_level: 77.654 + index * 2.31,
  }));
  const target = targetRows[3];
  const stop = auditRows[3];
  const retestZone = {
    date: "2021-01-04", ma: 90.123, retest_zone_low: 90.033, retest_zone_high: 90.213,
    low: 89, high: 92, close: 91, intersects: true,
  };
  const chart = {
    daily_data: [bar], events: [event],
    target_outcomes: targetRows, target_session_audit: auditRows,
    failures: [{ event_id: "e1", terminal_outcome: "SIDEWAYS", sideways_window_bars: 4,
      sideways_window_start: "2021-01-03", sideways_window_end: "2021-01-06",
      sideways_window_high: 102.4, sideways_window_low: 99.1, sideways_atr14: 2.2,
      sideways_range_atr: 1.5, retest_zone_history: [retestZone] }],
  };
  const model = prepareMaAnalyticsChart(chart, "e1", {
    targetType: "ATR_1.5", condition: "DAY2_SUCCESS_AND_VOL_GE_20", origin: "POST_D2_SUCCESS",
  });
  assert.equal(model.selectedEvent.reference_entry, 111.123);
  assert.equal(model.selectedEvent.volume_change, 0.27);
  assert.equal(model.selectedEvent.vol_ge_10, true);
  assert.equal(model.selectedEvent.vol_ge_20, true);
  assert.equal(model.selectedEvent.vol_ge_30, false);
  assert.equal(model.failure.sideways_window_bars, 4);
  assert.equal(model.failure.sideways_range_atr, 1.5);
  assert.equal(model.selectedTarget, target);
  assert.equal(model.selectedTarget.target_level, 237.891 + 3 * 11.117);
  assert.deepEqual(model.stopAudit, [stop]);
  assert.equal(model.stopAudit[0].stop_level, 77.654 + 3 * 2.31);
  assert.deepEqual(model.retestZoneHistory, [retestZone]);
  assert.equal(model.retestZoneHistory[0].retest_zone_low, 90.033);
  assert.equal(model.bars[0].box_high_at_session_start, 109.876);
  assert.equal(model.bars[0].box_low_at_session_start, 88.765);
  assert.deepEqual(MA_ANALYTICS_TARGET_TYPES, ["PCT_3", "ATR_0.5", "ATR_1", "ATR_1.5", "ATR_2", "ATR_3"]);
  assert.deepEqual(MA_ANALYTICS_OBSERVATION_ORIGINS, ["POST_D1", "POST_D2_SUCCESS"]);
  for (const [index, targetType] of MA_ANALYTICS_TARGET_TYPES.entries()) {
    const selected = prepareMaAnalyticsChart(chart, "e1", {
      targetType, condition: "DAY2_SUCCESS_AND_VOL_GE_20", origin: "POST_D2_SUCCESS",
    });
    assert.equal(selected.selectedTarget.target_level, 237.891 + index * 11.117);
    assert.equal(selected.stopAudit[0].stop_level, 77.654 + index * 2.31);
  }
  assert.equal(MA_ANALYTICS_TERMINAL_LABELS.SIDEWAYS, "價格區間整理");
});

test("analytics box overlay is a causal staircase, not an interpolated diagonal", () => {
  const bars = [
    { box_id_at_session_start: "b1", box_high_at_session_start: 100 },
    { box_id_at_session_start: "b1", box_high_at_session_start: 100 },
    { box_id_at_session_start: "b1", box_high_at_session_start: 105 },
  ];
  const path = buildAnalyticsBoundaryPath(bars, "box_high_at_session_start", index => index * 10, value => value);
  assert.equal(path, "M0.0,100.0 L10.0,100.0 L20.0,100.0 L20.0,105.0");
});

test("Day2 marker renders on the backend-selected date even when event_ids is empty", () => {
  const event = {
    event_id: "e1", d1_date: "2021-01-01", d2_date: "2021-01-04",
    d2_status: "SUCCESS", d2_success: true,
  };
  const bars = [
    { date: "2021-01-01", event_ids: ["e1"], close: 100 },
    { date: "2021-01-04", event_ids: [], close: 90 },
  ];
  assert.equal(bars[1].event_ids.length, 0);
  assert.equal(buildAnalyticsDay2Marker(bars[0], event), null);
  const marker = buildAnalyticsDay2Marker(bars[1], event);
  assert.deepEqual(marker, {
    eventId: "e1", date: "2021-01-04", status: "SUCCESS", label: "二日法則成立",
  });
  assert.notEqual(event.d2_date, event.d1_date);
  // The deliberately conflicting D2 close is not consulted to derive status.
  assert.ok(bars[1].close < bars[0].close);
  assert.equal(marker.status, event.d2_status);
});

test("Day2 marker status labels preserve backend SUCCESS, FAILURE, and NOT_EVALUABLE", () => {
  for (const [status, label] of [
    ["SUCCESS", "二日法則成立"],
    ["FAILURE", "二日法則失敗"],
    ["NOT_EVALUABLE", "二日法則無法評估"],
  ]) {
    const marker = buildAnalyticsDay2Marker(
      { date: "2021-01-04", event_ids: [] },
      { event_id: "e1", d2_date: "2021-01-04", d2_status: status },
    );
    assert.equal(marker.status, status);
    assert.equal(marker.label, label);
    assert.equal(MA_ANALYTICS_DAY2_STATUS_LABELS[marker.status], label);
  }
});

test("Day2 marker follows the selected event after nearby-period chart switching", () => {
  const makeChart = (eventId, d2Status) => ({
    daily_data: [{ date: `${eventId}-d2`, event_ids: [], close: 1 }],
    events: [{ event_id: eventId, d1_date: `${eventId}-d1`, d2_date: `${eventId}-d2`, d2_status: d2Status }],
  });
  const period23 = prepareMaAnalyticsChart(makeChart("sma23", "FAILURE"), "sma23");
  const period24 = prepareMaAnalyticsChart(makeChart("sma24", "SUCCESS"), "sma24");
  assert.equal(buildAnalyticsDay2Marker(period23.bars[0], period23.selectedEvent).status, "FAILURE");
  assert.equal(buildAnalyticsDay2Marker(period24.bars[0], period24.selectedEvent).status, "SUCCESS");
  assert.equal(period23.selectedEvent.event_id, "sma23");
  assert.equal(period24.selectedEvent.event_id, "sma24");
});

test("dynamic stop 98.5 to 99.0 is drawn horizontal then vertical, never diagonal", () => {
  const dateIndex = new Map([["D2", 0], ["D3", 1]]);
  const path = buildAnalyticsStopPath([
    { date: "D2", stop_level: 98.5 },
    { date: "D3", stop_level: 99.0 },
  ], dateIndex, index => index * 10, value => value);
  assert.equal(path, "M0,98.5 L10,98.5 L10,99");
  assert.notEqual(path, "M0,98.5 L10,99");
});

test("dynamic stop builds multiple steps, while repeated stops remain horizontal", () => {
  const dateIndex = new Map([["D2", 0], ["D3", 1], ["D4", 2], ["D5", 3]]);
  const stepped = buildAnalyticsStopPath([
    { date: "D2", stop_level: 98.5 },
    { date: "D3", stop_level: 99.0 },
    { date: "D4", stop_level: 99.0 },
    { date: "D5", stop_level: 99.3 },
  ], dateIndex, index => index * 10, value => value);
  assert.equal(stepped, "M0,98.5 L10,98.5 L10,99 L20,99 L30,99 L30,99.3");
  assert.equal(stepped.endsWith("L30,99.3"), true);
  assert.equal(stepped.includes("L40"), false);
  const flat = buildAnalyticsStopPath([
    { date: "D2", stop_level: 98.5 },
    { date: "D3", stop_level: 98.5 },
    { date: "D4", stop_level: 98.5 },
  ], dateIndex, index => index * 10, value => value);
  assert.equal(flat, "M0,98.5 L10,98.5 L20,98.5");
});

test("dynamic stop order follows supplied trading sessions rather than calendar-day filling", () => {
  const tradingIndex = new Map([["2021-01-04", 0], ["2021-01-06", 1]]);
  const path = buildAnalyticsStopPath([
    { date: "2021-01-06", stop_level: 99 },
    { date: "2021-01-04", stop_level: 98.5 },
  ], tradingIndex, index => index * 10, value => value);
  assert.equal(path, "M0,98.5 L10,98.5 L10,99");
});

test("POST_D1 and POST_D2_SUCCESS use separate backend stop audits, including short-side values", () => {
  const chart = {
    daily_data: [
      { date: "D2", sma: 100, close: 110, event_ids: [] },
      { date: "D3", sma: 100, close: 111, event_ids: [] },
    ],
    events: [{ event_id: "e1", direction: "SHORT", d1_date: "D1", d2_date: "D2", d2_status: "SUCCESS" }],
    target_session_audit: [
      { event_id: "e1", target_type: "PCT_3", condition_type: "BREAKOUT", observation_origin: "POST_D1", date: "D2", stop_level: 91.234 },
      { event_id: "e1", target_type: "PCT_3", condition_type: "BREAKOUT", observation_origin: "POST_D1", date: "D3", stop_level: 92.345 },
      { event_id: "e1", target_type: "PCT_3", condition_type: "BREAKOUT", observation_origin: "POST_D2_SUCCESS", date: "D3", stop_level: 87.654 },
    ],
  };
  const indices = new Map([["D2", 0], ["D3", 1]]);
  const x = index => index * 10;
  const y = value => value;
  const postD1 = prepareMaAnalyticsChart(chart, "e1", { targetType: "PCT_3", condition: "BREAKOUT", origin: "POST_D1" });
  const postD2 = prepareMaAnalyticsChart(chart, "e1", { targetType: "PCT_3", condition: "BREAKOUT", origin: "POST_D2_SUCCESS" });
  assert.deepEqual(postD1.stopAudit.map(row => row.stop_level), [91.234, 92.345]);
  assert.deepEqual(postD2.stopAudit.map(row => row.stop_level), [87.654]);
  assert.notEqual(buildAnalyticsStopPath(postD1.stopAudit, indices, x, y), buildAnalyticsStopPath(postD2.stopAudit, indices, x, y));
  assert.equal(postD1.stopAudit[0].stop_level, 91.234); // not SMA × 0.985
  assert.equal(postD2.stopAudit[0].stop_level, 87.654);
  assert.equal(postD1.selectedEvent.direction, "SHORT");
});

test("chart component renders backend D2 status and stop staircase without recalculation", () => {
  const component = readFileSync(new URL("../components/MaBreakoutAnalyticsStudy.tsx", import.meta.url), "utf8");
  assert.match(component, /buildAnalyticsDay2Marker\(bar,selected\)/);
  assert.match(component, /eventDay&&<circle data-marker-type="DAY1"/);
  assert.match(component, /data-marker-type="DAY2"[^>]*data-day2-status=\{day2Marker\.status\}/);
  assert.match(component, /backend status=\$\{day2Marker\.status\}/);
  assert.match(component, /data-day2-status=\{selected\.d2_status\}/);
  assert.match(component, /buildAnalyticsStopPath\(selectedAudit,idxByDate,x,y\)/);
  assert.match(component, /<path d=\{stopPath\} data-stop-audit-origin=\{origin\}/);
  assert.doesNotMatch(component, /<polyline points=\{stopPath\}/);
  assert.doesNotMatch(component, /d2_close\s*[<>]=?/);
});

test("analytics chart empty state does not invent strategy values", () => {
  assert.deepEqual(prepareMaAnalyticsChart(null, null), {
    bars: [], events: [], selectedEvent: null, targets: [], selectedTarget: null,
    stopAudit: [], failure: null, retestZoneHistory: [], selectedTargetType: "PCT_3",
    selectedCondition: "BREAKOUT", selectedOrigin: "POST_D1",
  });
});

test("long and short aggregates remain visibly separated in every probability table", () => {
  const component = readFileSync(new URL("../components/MaBreakoutAnalyticsStudy.tsx", import.meta.url), "utf8");
  assert.equal((component.match(/<th>方向<\/th>/g) ?? []).length, 3);
  assert.match(component, /Long \$\{fmtPct\(day2ProbabilityByDirection\.get\("LONG"\)\)\} \/ Short/);
});
