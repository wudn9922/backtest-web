import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require=createRequire(import.meta.url);
const i18nJs=ts.transpileModule(fs.readFileSync(new URL("../lib/i18n.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const language={exports:{}};new Function("require","module","exports",i18nJs)(require,language,language.exports);
const componentJs=ts.transpileModule(fs.readFileSync(new URL("../components/VolatilityManagedStudy.tsx",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const module={exports:{}};new Function("require","module","exports",componentJs)(id=>id==="@/lib/i18n"?language.exports:require(id),module,module.exports);

test("volatility benchmark is a responsive read-only Traditional Chinese summary",()=>{
  const metric={total_return:1,cagr:.08,annualized_volatility:.12,mdd:-.2,sharpe:.8,sortino:1,calmar:.4,exposure:.75,cash_pct:.25,turnover:3,commission:10,slippage:4,cash_interest:5,number_of_trades:20};
  const delta={total_return:-.1,cagr:-.01,mdd:.1,sharpe:.2,sortino:.3,calmar:.1,exposure:-.25,turnover:2};
  const study={study:"VOL_MANAGED_20D_15PCT_CAP1",title:"20 日波動度管理曝險",evidence_grade:"NOT SUPPORTED",next_family:"NONE",registration:{snapshot_id:"env3-test",spec_sha256:"a".repeat(64),fingerprint:"b".repeat(64)},evaluation:{evaluation_start:"2010-02-03",evaluation_end:"2026-09-01"},primary_spy:{CASH_ZERO:{managed:metric,buy_hold:metric,delta}},robustness_summary:{CASH_ZERO:{etfs:14,improvement_counts:{sharpe:9,mdd:14,calmar:8},median_delta:{sharpe:.1,mdd:.1,calmar:.05},median_managed_exposure:.7,median_cagr_sacrifice:-.01}},crisis_analysis:{CASH_ZERO:[{delta:{mdd:.1},minimum_target_exposure:.2}]},cost_stress_spy:{CASH_ZERO:{"2X_BOTH":{managed:metric,buy_hold:metric,delta}}},cash_decomposition:{SPY:{managed_return_contribution_pp:2,incremental_managed_cash_effect_pp:1.5}},walk_forward_summary:{spy_unique_tests:{cells:20,sharpe:12,mdd:15},all_etf_unique_tests:{}}};
  const html=renderToStaticMarkup(React.createElement(module.exports.VolatilityManagedStudy,{study}));
  for(const value of ["波動度管理曝險基準研究","20 日波動度","15% 目標波動","最高 100% 股票曝險","9 / 14","env3-test","volatility-managed-benchmark"]){assert.ok(html.includes(value),value);}
  assert.ok(html.includes("min-h-11"));
  assert.ok(html.includes("break-all"));
  assert.ok(!html.includes("VOL_001"));
  assert.ok(!html.includes("<table"));
});
