import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const css = fs.readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const settings = fs.readFileSync(new URL("../components/SettingsPanel.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const charts = fs.readFileSync(new URL("../components/Charts.tsx", import.meta.url), "utf8");
const inspector = fs.readFileSync(new URL("../components/PositionInspector.tsx", import.meta.url), "utf8");
const diagnostic = fs.readFileSync(new URL("../components/Day1StopDiagnostic.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const defaultForm = fs.readFileSync(new URL("../lib/default-form.ts", import.meta.url), "utf8");

test("mobile layout has a sticky safe-area run action and no page overflow", () => {
  assert.match(css, /position:\s*fixed/);
  assert.match(css, /env\(safe-area-inset-bottom\)/);
  assert.match(css, /overflow-x:\s*hidden/);
});

test("advanced settings are collapsible and numeric inputs request numeric keyboards", () => {
  assert.match(settings, /<details className="settings-section"/);
  assert.match(settings, /inputMode=/);
  assert.match(settings, /Extreme Take Profit/);
  assert.match(settings, /Use recent test range/);
  assert.match(settings, /tradingDays < 20/);
  assert.match(settings, /Daily Intrabar Assumption/);
  assert.match(settings, /OHLC Heuristic/);
  assert.match(settings, /Favorable/);
  assert.match(settings, /Market data provider/);
  assert.match(settings, /Auto \(cache → Yahoo → Stooq\)/);
});

test("advanced day1 stop strategy is selectable with its isolated risk parameter", () => {
  assert.match(settings, /Advanced \+ Day1 3% Stop/);
  assert.match(settings, /advanced_day1_stop/);
  assert.match(settings, /Day 1 Stop Below MA %/);
  assert.match(defaultForm, /day1_stop_pct:\s*3/);
  assert.match(inspector, /Day1 Stop/);
  assert.match(charts, /day1_stop/);
});

test("mobile records replace wide desktop tables", () => {
  assert.match(css, /\.desktop-table\s*\{\s*display:\s*none/);
  assert.match(css, /\.mobile-records\s*\{\s*display:\s*grid/);
});

test("browser API calls default to same-origin and charts enable pinch gestures", () => {
  assert.match(api, /NEXT_PUBLIC_API_BASE_URL/);
  assert.doesNotMatch(api, /localhost:8000|127\.0\.0\.1:8000/);
  assert.match(charts, /pinch:\s*true/);
});

test("daily-only errors expose request context without intraday fields", () => {
  assert.match(api, /daily_bars_count/);
  assert.match(api, /execution_model/);
  assert.doesNotMatch(api, /intraday_bars_count|execution_timeframe/);
  assert.match(api, /yahoo_error/);
});

test("position audit is loaded on demand and exposes mobile inspector details", () => {
  assert.match(api, /positions\/\$\{encodeURIComponent\(positionId\)\}\/audit/);
  assert.match(page, /View Details/);
  assert.match(page, /api\.positionAudit\(backtestId, positionId\)/);
  assert.match(inspector, /Daily strategy timeline/);
  assert.match(inspector, /item\.ambiguity\.message/);
  assert.match(inspector, /Entry Day Volume/);
  assert.match(inspector, /Day 2 Confirmation/);
  assert.match(charts, /Break low/);
  assert.match(charts, /Protective/);
});

test("day1 stop diagnostic is lazy and links both strategy outcomes to the inspector", () => {
  assert.match(api, /diagnostics\/day1-stop/);
  assert.match(page, /api\.day1StopDiagnostic\(result\.id\)/);
  assert.match(page, /item !== "Diagnostic"/);
  assert.match(diagnostic, /Every DAY1_FULL_STOP/);
  assert.match(diagnostic, /Largest return damage/);
  assert.match(diagnostic, /Largest improvements/);
  assert.match(diagnostic, /onInspect\(row\.baseline_backtest_id/);
  assert.match(diagnostic, /onInspect\(row\.variant_backtest_id/);
  assert.match(api, /diagnostics\/ambiguity-sensitivity/);
  assert.match(diagnostic, /Run Ambiguity Sensitivity/);
  assert.match(diagnostic, /messages\.sensitivityTitle\(report\.strategy_version\)/);
  assert.match(diagnostic, /ENTRY_ZONE_MISSED/);
  assert.match(diagnostic, /Same-policy matched delta/);
  assert.match(diagnostic, /messages\.legacyEntries/);
});
