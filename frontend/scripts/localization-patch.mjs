// One-off mechanical migration. Prints source pairs for apply_patch; never writes files.
import fs from "node:fs";
import ts from "typescript";
const files = ["app/page.tsx", "components/SettingsPanel.tsx", "components/PositionInspector.tsx", "components/Day1StopDiagnostic.tsx", "components/Charts.tsx"];
const decode = value => value.replaceAll("&apos;", "'").replaceAll("&amp;", "&").replaceAll("&gt;", ">").replaceAll("&lt;", "<");
const records=[];
for (const file of files) {
  const before=fs.readFileSync(file,"utf8");
  const source=ts.createSourceFile(file,before,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const edits=[];
  function visit(node) {
    if (ts.isJsxText(node) && /[A-Za-z]/.test(node.text)) {
      const content=decode(node.text.trim().replace(/\s+/g," "));
      edits.push([node.pos,node.end,`{t(${JSON.stringify(content)})}`]);
    } else if (ts.isJsxAttribute(node) && ["title","subtitle","label","aria-label","hint"].includes(node.name.text) && node.initializer && ts.isStringLiteral(node.initializer)) {
      edits.push([node.initializer.getStart(source),node.initializer.end,`{t(${JSON.stringify(decode(node.initializer.text))})}`]);
    }
    ts.forEachChild(node,visit);
  }
  visit(source);
  let after=before;
  for (const [a,b,value] of edits.sort((a,b)=>b[0]-a[0])) after=after.slice(0,a)+value+after.slice(b);
  after=after.replace('"use client";', '"use client";\n\nimport { t, messages, money as formatMoney, num, shares, dateText, displayValue, warningText, errorText } from "@/lib/i18n";');
  for (const name of ["label","title","subtitle","hint","status","item","name"]) {
    after=after.replaceAll(`{${name}}`,`{t(${name})}`);
  }
  for (const expr of ["strategyLabels[form.strategy]","strategyLabels[item]","progressStage","runLabel","item.strategy_state_at_open","item.strategy_state_at_close","event.event","event.state_before","event.state_after","entryZone.intrabar_assumption","row.day1_stop_strategy.exit_reason","label[row.policy]","row.match_status"]) {
    after=after.replaceAll(`{${expr}}`,`{t(${expr})}`);
  }
  after=after.replaceAll('{key.replaceAll("_"," ")}','{t(key)}').replaceAll('{c.replaceAll("_"," ")}','{t(c)}');
  after=after.replaceAll('label={key.replaceAll("_"," ")}','label={t(key)}');
  records.push({file,before,after});
}
process.stdout.write(JSON.stringify(records));
