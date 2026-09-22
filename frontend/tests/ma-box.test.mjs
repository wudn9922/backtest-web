import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { buildStepBoundaryPath } from "../lib/chartBoundary.mjs";
import { focusWindow, panViewport, resetZoom, zoomIn, zoomOut } from "../lib/chartViewport.mjs";
import { MA_BOX_REQUIREMENT_BINDINGS } from "../lib/maBoxRequirementBindings.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const root = path.resolve(process.cwd());
const component = fs.readFileSync(path.join(root, "components", "MaBoxStudy.tsx"), "utf8");
const page = fs.readFileSync(path.join(root, "app", "ma-box", "page.tsx"), "utf8");
const api = fs.readFileSync(path.join(root, "lib", "api.ts"), "utf8");

// Explicit machine-readable bindings consumed by the cross-language
// traceability validator; requirement coverage is not inferred from names.
export { MA_BOX_REQUIREMENT_BINDINGS };

test("MA_BOX_LONG_V1 has a dedicated page and does not enter the legacy selector", () => {
  assert.match(page, /MaBoxStudy/);
  assert.match(component, /MA_BOX_LONG_V1/);
  assert.match(component, /MA_LONG_BASELINE/);
  assert.match(component, /BUY_AND_HOLD/);
  assert.doesNotMatch(component, /strategy:\s*["']simple["']/);
});

test("MA_BOX page exposes the frozen Traditional Chinese semantics", () => {
  assert.match(component, /均線箱型長期比較/);
  assert.match(component, /固定：SMA、OHLC Heuristic、MA−1\.5% 停損、無固定停利/);
  assert.match(component, /附近 SMA 比較/);
  assert.match(component, /完整 K 線與箱型 audit/);
  assert.match(component, /下載 audit JSON/);
});

test("MA_BOX page provides nearby period switching and counterfactual display", () => {
  assert.match(component, /study\.periods\.map/);
  assert.match(component, /setPeriod\(p\)/);
  assert.match(component, /counterfactual_summary/);
  assert.match(component, /Box filter counterfactual/);
});

test("MA_BOX study API uses its dedicated studies namespace", () => {
  assert.match(api, /\/api\/ma-box\/studies/);
  assert.match(api, /createMaBoxStudy/);
});

test("MA_BOX chart includes stop, box overlays and trade export controls", () => {
  assert.match(component, /active_stop/);
  assert.match(component, /箱型邊界/);
  assert.match(component, /下載交易 CSV/);
});

test("MA_BOX boundary renderer is causal and stepwise", () => {
  const rows = [
    { box_id: "box-1", box_high_effective: 100, box_low_effective: 90 },
    { box_id: "box-1", box_high_effective: 100, box_low_effective: 90 },
    { box_id: "box-1", box_high_effective: 105, box_low_effective: 90 },
  ];
  const path = buildStepBoundaryPath(rows, "box_high_effective", i => i * 10, value => value);
  assert.equal(path, "M0.0,100.0 L10.0,100.0 L20.0,100.0 L20.0,105.0");
  assert.doesNotMatch(path, /L20\.0,105\.0 L/);
  assert.deepEqual(MA_BOX_REQUIREMENT_BINDINGS["MA_BOX boundary renderer is causal and stepwise"], ["REV3-09"]);
});

test("MA_BOX zoom, reset, focus and horizontal-pan contracts are deterministic", () => {
  assert.equal(zoomIn(1), 1.25);
  assert.equal(zoomOut(1), 1);
  assert.equal(zoomIn(3), 3);
  assert.equal(resetZoom(), 1);
  assert.deepEqual(focusWindow(100, 50, 60), { start: 30, end: 70 });
  assert.deepEqual(focusWindow(100, null, null), { start: 0, end: 99 });
  assert.deepEqual(panViewport({ from: 20, to: 80 }, 10, { min: 0, max: 100 }), { from: 30, to: 90 });
  assert.deepEqual(panViewport({ from: 20, to: 80 }, -50, { min: 0, max: 100 }), { from: 0, to: 60 });
  assert.deepEqual(panViewport({ from: 20, to: 80 }, 50, { min: 0, max: 100 }), { from: 40, to: 100 });

  // Parse the production TSX contract instead of relying on a source-string
  // regex: the real component must import the same pure helper, call it from
  // its handlePan state transition, and wire that handler to onScroll.
  const source = ts.createSourceFile("MaBoxStudy.tsx", component, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let importedPanViewport = false;
  let handlePanBody = null;
  let onScrollUsesHandlePan = false;
  function visit(node) {
    if (ts.isImportDeclaration(node) && node.moduleSpecifier.text === "@/lib/chartViewport.mjs") {
      importedPanViewport = node.importClause?.namedBindings?.elements?.some(item => item.name.text === "panViewport") ?? false;
    }
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === "handlePan") handlePanBody = node.initializer;
    if (ts.isJsxAttribute(node) && node.name.text === "onScroll" && node.initializer?.expression?.getText(source) === "handlePan") {
      onScrollUsesHandlePan = true;
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.equal(importedPanViewport, true);
  assert.ok(handlePanBody);
  let callsPanViewport = false;
  let updatesPanOffset = false;
  function inspectHandler(node) {
    if (ts.isCallExpression(node) && node.expression.getText(source) === "panViewport") callsPanViewport = true;
    if (ts.isCallExpression(node) && node.expression.getText(source) === "setPanOffset") {
      updatesPanOffset = node.arguments.some(argument => argument.getText(source).includes("next.from"));
    }
    ts.forEachChild(node, inspectHandler);
  }
  inspectHandler(handlePanBody);
  assert.equal(callsPanViewport, true);
  assert.equal(updatesPanOffset, true);
  assert.equal(onScrollUsesHandlePan, true);
  assert.deepEqual(MA_BOX_REQUIREMENT_BINDINGS["MA_BOX zoom, reset, focus and horizontal-pan contracts are deterministic"], ["REV3-09"]);
});
