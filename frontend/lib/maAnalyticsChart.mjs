/** Frozen chart selectors; levels and classifications always come from backend rows. */
export const MA_ANALYTICS_TARGET_TYPES = Object.freeze([
  "PCT_3", "ATR_0.5", "ATR_1", "ATR_1.5", "ATR_2", "ATR_3",
]);

export const MA_ANALYTICS_OBSERVATION_ORIGINS = Object.freeze([
  "POST_D1", "POST_D2_SUCCESS",
]);

export const MA_ANALYTICS_TERMINAL_LABELS = Object.freeze({
  MA_RETEST_REBOUND: "均線回測反彈",
  MA_RETEST_REJECTION: "均線回測受壓",
  RETURN_TO_BEAR: "收盤返回均線下方",
  RETURN_TO_BULL: "收盤返回均線上方",
  TREND_CONTINUATION_AWAY: "趨勢延續並遠離均線",
  SIDEWAYS: "價格區間整理",
  RIGHT_CENSORED: "觀察期結束／右設限",
});

export const MA_ANALYTICS_DAY2_STATUS_LABELS = Object.freeze({
  SUCCESS: "二日法則成立",
  FAILURE: "二日法則失敗",
  NOT_EVALUABLE: "二日法則無法評估",
  RIGHT_CENSORED: "二日資料右設限",
});

/** Return the selected event's backend-authored D2 marker for this bar, if any. */
export function buildAnalyticsDay2Marker(bar, selectedEvent) {
  if (!bar || !selectedEvent || selectedEvent.d2_date !== bar.date) return null;
  const status = String(selectedEvent.d2_status ?? "NOT_EVALUABLE");
  return {
    eventId: selectedEvent.event_id,
    date: bar.date,
    status,
    label: MA_ANALYTICS_DAY2_STATUS_LABELS[status] ?? status,
  };
}

/** Build an SVG staircase from only the selected backend stop-audit sessions. */
export function buildAnalyticsStopPath(rows, indexByDate, x, y) {
  const points = rows.map(row => ({
    index: indexByDate.get(row.date),
    value: row.stop_level,
  })).filter(point => point.index != null && typeof point.value === "number" && Number.isFinite(point.value))
    .sort((left, right) => left.index - right.index);
  if (!points.length) return "";

  let path = `M${x(points[0].index)},${y(points[0].value)}`;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const currentX = x(current.index);
    path += ` L${currentX},${y(previous.value)}`;
    if (previous.value !== current.value) {
      path += ` L${currentX},${y(current.value)}`;
    }
  }
  return path;
}

/** Select a backend outcome/audit without deriving target or stop prices. */
export function prepareMaAnalyticsChart(chart, selectedEventId, selection = {}) {
  if (!chart) return {
    bars: [], events: [], selectedEvent: null, targets: [], selectedTarget: null,
    stopAudit: [], failure: null, retestZoneHistory: [],
    selectedTargetType: selection.targetType ?? "PCT_3",
    selectedCondition: selection.condition ?? "BREAKOUT",
    selectedOrigin: selection.origin ?? "POST_D1",
  };

  const events = chart.events ?? [];
  const selectedEvent = events.find(event => event.event_id === selectedEventId) ?? null;
  const targets = (chart.target_outcomes ?? []).filter(item => item.event_id === selectedEventId);
  const selectedTargetType = selection.targetType ?? "PCT_3";
  const selectedCondition = selection.condition ?? "BREAKOUT";
  const selectedOrigin = selection.origin ?? "POST_D1";
  const selectedTarget = targets.find(item => item.target_type === selectedTargetType
    && item.condition_type === selectedCondition
    && item.observation_origin === selectedOrigin) ?? null;
  const stopAudit = (chart.target_session_audit ?? []).filter(item => item.event_id === selectedEventId
    && item.target_type === selectedTargetType
    && item.condition_type === selectedCondition
    && item.observation_origin === selectedOrigin);
  const failure = (chart.failures ?? []).find(item => item.event_id === selectedEventId) ?? null;
  return {
    bars: chart.daily_data ?? [], events, selectedEvent, targets, selectedTarget,
    stopAudit, failure, retestZoneHistory: failure?.retest_zone_history ?? [],
    selectedTargetType, selectedCondition, selectedOrigin,
  };
}

/** Build a staircase from backend-authoritative session-start boundaries. */
export function buildAnalyticsBoundaryPath(rows, valueKey, x, y) {
  let path = "";
  let previous = null;
  rows.forEach((row, index) => {
    const value = Number(row[valueKey]);
    const boxId = String(row.box_id_at_session_start ?? "");
    if (!Number.isFinite(value) || !boxId) {
      previous = null;
      return;
    }
    if (!previous || previous.boxId !== boxId) {
      path += `${path ? " " : ""}M${x(index).toFixed(1)},${y(value).toFixed(1)}`;
    } else if (Math.abs(previous.value - value) > 1e-10) {
      path += ` L${x(index).toFixed(1)},${y(previous.value).toFixed(1)} L${x(index).toFixed(1)},${y(value).toFixed(1)}`;
    } else {
      path += ` L${x(index).toFixed(1)},${y(value).toFixed(1)}`;
    }
    previous = { value, boxId };
  });
  return path;
}
