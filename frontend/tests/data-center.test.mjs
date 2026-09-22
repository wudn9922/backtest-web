import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../app/data/page.tsx", import.meta.url), "utf8");
const research = fs.readFileSync(new URL("../app/research/page.tsx", import.meta.url), "utf8");
const dashboard = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const copy = fs.readFileSync(new URL("../lib/i18n.ts", import.meta.url), "utf8");

test("data center is a Traditional Chinese zero-terminal control surface", () => {
  for (const label of ["資料中心","補齊研究資料","下載／更新無風險利率","重新檢查","背景工作","繼續重試失敗項目","資料連線需要修復","修復資料連線","受限","驗證失敗"])
    assert.match(copy, new RegExp(label));
  assert.match(page, /api\.fillResearchData/);
  assert.match(page, /api\.updateRiskFree/);
  assert.match(page, /api\.checkProviders/);
  assert.match(page, /api\.repairProviderConnectivity/);
  assert.doesNotMatch(page, /PowerShell|CMD|Terminal|npm|python|Set-ExecutionPolicy/i);
});

test("jobs expose polling, progress, partial failure and resume", () => {
  assert.match(page, /setInterval\(load,1500\)/);
  assert.match(page, /progress_current/);
  assert.match(page, /progress_total/);
  assert.match(page, /PARTIAL_SUCCESS/);
  assert.match(page, /api\.retryJob/);
  assert.match(page, /technical-details/);
});

test("research revalidation is readiness-gated and background-only", () => {
  assert.match(research, /readiness\.research_validation_ready/);
  assert.match(research, /api\.validateResearchEnvironment/);
  assert.match(research, /RESEARCH_ENVIRONMENT_VALIDATION/);
  assert.match(research, /Research jobs/);
});

test("research page fetches the latest completed immutable environment snapshot", () => {
  assert.match(api, /researchEnvironmentCurrent/);
  assert.match(api, /\/api\/research\/environment\/current/);
  assert.match(api, /cache: "no-store"/);
  assert.match(research, /api\.researchEnvironmentCurrent\(\)/);
  assert.match(research, /environment_snapshot_id/);
  assert.match(research, /Current research environment snapshot/);
  assert.match(research, /setInterval\(load,1500\)/);
});

test("data center uses mobile cards and large touch targets", () => {
  assert.match(page, /min-h-12/);
  assert.match(page, /sm:grid-cols-2/);
  assert.match(page, /<details/);
  assert.doesNotMatch(page, /onMouseEnter|onMouseOver/);
});

test("all user actions use same-origin backend APIs and dashboard links data center", () => {
  for (const route of ["/api/data-center","/api/system/status","/api/jobs/research-market-data","/api/jobs/risk-free-data","/api/jobs/provider-connectivity-check","/api/jobs/provider-connectivity-repair","/api/jobs/research-environment-validation"])
    assert.match(api, new RegExp(route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(dashboard, /href="\/data"/);
  assert.doesNotMatch(api, /restart-backtest\.ps1/);
});
