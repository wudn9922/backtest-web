import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const file = new URL("../components/XsmomStudy.tsx", import.meta.url);
const js = ts.transpileModule(fs.readFileSync(file,"utf8"), {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const mod = {exports:{}};
const i18n = ts.transpileModule(fs.readFileSync(new URL("../lib/i18n.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const lang = {exports:{}};
new Function("require","module","exports",i18n)(require,lang,lang.exports);
new Function("require","module","exports",js)(id=>id==="@/lib/i18n"?lang.exports:require(id),mod,mod.exports);

test("read-only momentum summary renders Chinese metrics, provenance and no candidate action",()=>{
  const metric={total_return:1,cagr:.1,mdd:-.2,sharpe:.8,exposure:.99,turnover:12};
  const study={study:"XSMOM_12_1_TOP3",grade:"NOT SUPPORTED",evaluation_start:"2011-02-01",evaluation_end:"2026-09-01",registration:{snapshot_id:"env3-test",spec_sha256:"a".repeat(64),fingerprint:"b".repeat(64)},cash_models:{CASH_ZERO:{RS:metric,EW:metric,SPY:metric,QQQ:metric}}};
  const html=renderToStaticMarkup(React.createElement(mod.exports.XsmomStudy,{study}));
  for(const text of ["橫斷面動能基準研究","12-1 相對強弱 Top 3","合格 ETF 全體等權","現金不計息","env3-test","100%","cross-sectional-momentum-benchmark"]){assert.ok(html.includes(text),text);}
  assert.ok(html.includes("break-all"));
  assert.ok(html.includes("min-h-11"));
  assert.ok(!html.includes("MOMENTUM_001"));
  assert.ok(!html.includes("<table"));
});
