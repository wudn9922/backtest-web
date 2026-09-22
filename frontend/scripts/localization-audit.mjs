import fs from "node:fs";
import ts from "typescript";
import { fileURLToPath } from "node:url";
const root=new URL("../",import.meta.url);
const code=ts.transpileModule(fs.readFileSync(new URL("lib/i18n.ts",root),"utf8"),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const i18n=await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
export { i18n };
export function auditSource(){
  const files=["app/page.tsx","app/layout.tsx","app/manifest.ts","app/not-found.tsx","app/error.tsx","components/SettingsPanel.tsx","components/PositionInspector.tsx","components/Day1StopDiagnostic.tsx","components/Charts.tsx"];
  const missing=[]; const calls=new Set(); const bare=[]; const arrayLabels=new Set();
  for(const file of files){
    const source=ts.createSourceFile(file,fs.readFileSync(new URL(file,root),"utf8"),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
    function visit(node){
      if(ts.isArrayLiteralExpression(node) && node.elements.length>=2 && ts.isStringLiteral(node.elements[0])){
        for(const item of node.elements.slice(0,2)){
          if(ts.isStringLiteral(item))arrayLabels.add(item.text);
        }
      }
      if(ts.isCallExpression(node) && node.expression.getText(source)==="t" && ts.isStringLiteral(node.arguments[0])){
        const key=node.arguments[0].text;calls.add(key);
        if(!i18n.hasTranslation(key)&&![/^SQLite \+ Parquet$/].some(x=>x.test(key)))missing.push({file,key});
      }
      if(ts.isJsxText(node)&&/[A-Za-z]/.test(node.text))bare.push({file,text:node.text.trim()});
      ts.forEachChild(node,visit);
    }visit(source);
  }
  const unmappedLabels=[...arrayLabels].filter(k=>!i18n.hasTranslation(k));
  return {files:files.length,static_translation_keys:calls.size,array_labels_checked:arrayLabels.size,unmapped_array_labels:unmappedLabels,untranslated_static_strings:[...missing,...bare],untranslated_count:missing.length+bare.length+unmappedLabels.length};
}
if(process.argv[1]===fileURLToPath(import.meta.url))console.log(JSON.stringify(auditSource(),null,2));
