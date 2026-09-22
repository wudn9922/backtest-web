import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../app/research/page.tsx", import.meta.url), "utf8");
const dashboard = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const settings = fs.readFileSync(new URL("../components/SettingsPanel.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");

test("research page exposes the fixed framework sections in Traditional Chinese translation flow", () => {
  for (const section of ["Research environment", "Research candidates", "Research baselines", "Strategy comparison", "Cross-asset", "Cross-period", "Cost stress", "Daily OHLC ordering sensitivity", "Winner concentration"])
    assert.match(page, new RegExp(section.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(page, /catalog\.registry\.candidates/);
  assert.match(page, /catalog\.provenance\.datasets/);
  assert.match(page, /catalog\.benchmark_viability/);
  assert.match(page, /catalog\.research_environment/);
  assert.match(page, /LONG-HISTORY|Long-history status/);
  assert.match(page, /Survivorship limitation/);
  assert.match(page, /CASH_RISK_FREE/);
  assert.match(page, /data_manifest\.sha256/);
  assert.match(page, /NEXT FAMILY/);
  assert.match(page, /api\/research\/reports/);
});

test("research catalog is lazy read-only same-origin API data", () => {
  assert.match(api, /researchFramework/);
  assert.match(api, /\/api\/research\/framework/);
  assert.doesNotMatch(api, /researchFramework:[\s\S]{0,120}method:\s*["']POST/);
});

test("production selector remains unchanged and M3 never appears in it", () => {
  assert.match(settings, /\["simple", "advanced", "advanced_day1_stop"\]/);
  assert.doesNotMatch(settings, /["']M3["']/);
  assert.match(settings, /Research baseline strategy/);
  assert.match(settings, /Historical research did not pass the strategy viability gate/);
  assert.match(dashboard, /href="\/research"/);
});

test("research page keeps wide data tables responsive", () => {
  assert.match(page, /desktop-table/);
  assert.match(page, /mobile-records/);
  assert.match(page, /overflow-x-auto/);
  assert.match(page, /break-words/);
});
