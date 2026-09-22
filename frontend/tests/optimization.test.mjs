import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const page=fs.readFileSync(new URL("../app/optimize/page.tsx",import.meta.url),"utf8");
const api=fs.readFileSync(new URL("../lib/api.ts",import.meta.url),"utf8");
const home=fs.readFileSync(new URL("../app/page.tsx",import.meta.url),"utf8");
const css=fs.readFileSync(new URL("../app/globals.css",import.meta.url),"utf8");
const i18n=fs.readFileSync(new URL("../lib/i18n.ts",import.meta.url),"utf8");

test("MA optimization is a Traditional Chinese canonical-engine tool",()=>{
  assert.match(page,/Parameter optimization/);
  assert.match(page,/canonical backtest engine/);
  assert.match(i18n,/參數最佳化/);
  assert.match(i18n,/均線週期最佳化/);
  assert.doesNotMatch(page,/candidate gate|NEXT FAMILY|block bootstrap/i);
});

test("range, 500-run guard, ranking and optional train-only selection are visible",()=>{
  assert.match(page,/maMin/);assert.match(page,/maMax/);assert.match(page,/maStep/);
  assert.match(page,/combinations<=500/);
  assert.match(page,/Out-of-sample validation/);
  assert.match(page,/Test data is never used to select/);
  assert.match(page,/sharpe_ratio/);
});

test("background job survives refresh and supports cancellation",()=>{
  assert.match(api,/\/api\/optimizations/);
  assert.match(api,/cancelOptimization/);
  assert.match(page,/setInterval/);
  assert.match(page,/api\.optimizations/);
  assert.match(api,/retryOptimization/);
  assert.match(page,/Skipped \/ insufficient history/);
  assert.match(page,/Failure stage/);
});

test("result tools include stability, performance and at most five equity curves",()=>{
  assert.match(page,/MA performance chart/);
  assert.match(page,/Nearby parameter performance/);
  assert.match(page,/values\.length<5/);
  assert.match(page,/Equity curve comparison/);
});

test("optimizer rows open or apply the exact canonical backtest",()=>{
  assert.match(page,/\?backtest_id=/);
  assert.match(page,/\?clone_backtest_id=/);
  assert.match(home,/query\.get\("backtest_id"\)/);
  assert.match(home,/query\.get\("clone_backtest_id"\)/);
});

test("optimization results use mobile cards instead of forcing the wide table",()=>{
  assert.match(page,/optimization-desktop/);
  assert.match(page,/optimization-mobile/);
  assert.match(css,/@media \(max-width: 900px\)[\s\S]*\.optimization-desktop/);
  assert.match(css,/\.optimization-mobile \{ display: grid; \}/);
  assert.match(page,/inputMode=\{decimal\?"decimal":"numeric"\}/);
});

test("rolling six-month mode is explicit, test-only, and mobile readable",()=>{
  assert.match(page,/rolling_6m/);
  assert.match(page,/Re-optimize every 6 months/);
  assert.match(page,/Fixed MA comparison/);
  assert.match(page,/6-month rolling results/);
  assert.match(page,/Test-only aggregate/);
  assert.match(page,/Selected MA history/);
  assert.match(page,/View complete test backtest/);
  assert.match(page,/Each 6-month test segment starts flat/);
  assert.match(page,/not continuous portfolio equity/i);
  assert.match(i18n,/每 6 個月重新最佳化/);
  assert.match(i18n,/未完成測試區間/);
});

test("rolling progress exposes current window and MA search progress",()=>{
  assert.match(page,/rolling_progress/);
  assert.match(page,/windows_total/);
  assert.match(page,/ma_current/);
  assert.match(page,/ma_total/);
  assert.match(page,/Train to test relationship/);
});

test("Structure V1 UI keeps raw, Wilson/ranking values and percentiles distinct",()=>{
  assert.match(page,/structure_ranking/);
  assert.match(page,/Wilson 下界/);
  assert.match(page,/排序值/);
  assert.match(page,/百分位/);
  assert.match(api,/structure_implementation_revision/);
  assert.match(page,/PRIOR_INVALIDATED_IMPLEMENTATION/);
});
