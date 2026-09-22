import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { i18n, auditSource } from "../scripts/localization-audit.mjs";

const require=createRequire(import.meta.url);
const root=fileURLToPath(new URL("../",import.meta.url));
const cache=new Map();
function load(file){
  if(cache.has(file))return cache.get(file);
  // Server-render localization checks, not a browser or a chart-layout simulator.
  if(file.endsWith("components/Charts.tsx"))return Object.fromEntries(["PositionAuditChart","StockChart","EquityChart","DrawdownChart","MonthlyHeatmap"].map(k=>[k,()=>React.createElement("div",{"data-test-chart":k})]));
  const source=fs.readFileSync(path.join(root,file),"utf8");
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
  const m={exports:{}};cache.set(file,m.exports);
  const localRequire=name=>{
    if(name.startsWith("@/")){
      const f=name.slice(2);const suffix=fs.existsSync(path.join(root,f+".tsx"))?".tsx":".ts";
      return load(f+suffix);
    }
    return require(name);
  };
  new Function("require","module","exports",code)(localRequire,m,m.exports);
  cache.set(file,m.exports);return m.exports;
}

const form={ticker:"NVDA",strategy:"advanced",start_date:"2021-09-01",end_date:"2026-09-01",initial_capital:100000,position_size_pct:100,commission_pct:.05,slippage_pct:.02,execution_model:"daily_conservative",execution_policy:"conservative",market_data_provider:"auto",force_close_at_end:true,parameters:{ma_type:"sma",ma_period:20,breakout_trigger_pct:1,entry_stop_pct:1.5,exit_below_ma_pct:1.5,volume_increase_pct:10,ma_risk_pct:1.5,first_tp_pct:3,bias_lookback:126,bias_sigma_multiple:2,atr_period:14,atr_multiple:2,extreme_tp_pct_q0:10,max_extreme_tp_count:3,minimum_position_pct_q0:20,day1_stop_pct:3}};

test("all current static UI copy is centrally translated",()=>{
  const result=auditSource();assert.equal(result.untranslated_count,0,JSON.stringify(result.untranslated_static_strings));
  assert.ok(result.static_translation_keys>200);
});
test("empty dashboard renders its secondary copy in Traditional Chinese",()=>{
  const {default:Dashboard}=load("app/page.tsx");
  const html=renderToStaticMarkup(React.createElement(Dashboard));
  assert.match(html,/回測實驗室/);assert.match(html,/設定參數並開始/);
  assert.match(html,/不利事件優先/);assert.match(html,/成交與事件/);
  assert.doesNotMatch(html,/>Adverse-first policy<|>Executions &amp; events<|>Configure and run/);
});
test("zh-TW money, share, percent and dates preserve numeric semantics",()=>{
  assert.equal(i18n.money(1234.56),"$1,234.56");
  assert.equal(i18n.shares(1294),"1,294 股");
  assert.equal(i18n.dateText("2024-06-25T04:00:00+00:00"),"2024-06-25");
  assert.equal(i18n.displayValue("return_pct",12.34),"12.34%");
  assert.equal(i18n.money(null),"—");
});
test("event translations do not mutate API values or infer trading state",()=>{
  const event={event:"FIRST_TP_TRIGGERED",state_after:"POST_FIRST_TP",price:126.441643,quantity:455};
  const before=JSON.stringify(event);
  assert.equal(i18n.t(event.event),"首次停利觸發");
  assert.equal(i18n.t("BREAK_PROTECTION_RESET"),"跌破保護重置");
  assert.equal(i18n.t("VOLUME_CONFIRMATION_FAIL"),"量能確認失敗");
  assert.equal(JSON.stringify(event),before);
  assert.equal(i18n.t("NVDA"),"NVDA");
  assert.equal(i18n.t("MA_EXIT"),"均線下方停損線全數出場");
  assert.equal(i18n.messages.simpleMaStopExit(1.5),"均線 −1.5% 停損出場");
  assert.equal(i18n.messages.maHalfStopLine(1.5),"均線 −1.5% 半倉停損");
});
test("errors distinguish connectivity, timeout, empty data and incomplete cache",()=>{
  assert.match(i18n.errorText("raw","CACHE_INCOMPLETE"),/快取涵蓋不完整/);
  assert.match(i18n.errorText("raw","PROVIDER_TIMEOUT"),/逾時/);
  assert.match(i18n.errorText("raw","NO_DATA"),/沒有日線/);
  assert.match(i18n.warningText("Yahoo currently unavailable — using cached market data."),/Yahoo 目前無法連線.*本機快取/);
  assert.match(i18n.errorText("Some upstream detail"),/技術詳細資訊/);
});
test("server-render all strategy settings and policy descriptions without changing request values",()=>{
  const {SettingsPanel}=load("components/SettingsPanel.tsx");
  for(const strategy of ["simple","advanced","advanced_day1_stop"]){
    for(const execution_policy of ["conservative","ohlc_heuristic","favorable"]){
      const value={...form,strategy,execution_policy};const before=JSON.stringify(value);
      const html=renderToStaticMarkup(React.createElement(SettingsPanel,{form:value,setForm:()=>{},running:false,progressStage:"",onRun:()=>{}}));
      assert.match(html,/執行回測/);assert.match(html,/前一交易日均線/);assert.match(html,/不是實際 tick 路徑/);
      assert.match(html,/value="conservative"/);assert.match(html,/value="advanced_day1_stop"|首日停損/);
      assert.doesNotMatch(html,/>Run Backtest<|>Risk Control<|>First take profit %</);
      assert.equal(JSON.stringify(value),before);
    }
  }
});
test("inspector renders Chinese states, inactive fields and English codes only in technical details",()=>{
  const {PositionInspector}=load("components/PositionInspector.tsx");
  const event={event:"FIRST_TP_TRIGGERED",state_before:"LONG_NORMAL",state_after:"POST_FIRST_TP",trigger_level:103,execution_price:103,shares_before:100,shares_sold:50,shares_remaining:50,metadata:{}};
  const audit={ticker:"NVDA",strategy:"advanced",position_id:"position-1",position:{entry_date:"2025-01-08",entry_price:100,q0:100,final_exit_date:"2025-01-09",final_return:.01,net_pnl:100,gross_pnl:110,fees:10,holding_days:2,exit_final_close_reason:"PROTECTIVE_STOP"},chart:{daily_data:[],executions:[]},timeline:[{date:"2025-01-08",timestamp:"2025-01-08",open:101,high:104,low:100.5,close:103,volume:1000,previous_day_ma:99,current_day_ma:100,previous_day_atr:3,bias_sigma:.03,current_quantity_at_open:100,current_quantity_at_close:50,strategy_state_at_open:"LONG_NORMAL",strategy_state_at_close:"POST_FIRST_TP",thresholds:{first_tp_price:103,protective_stop:null},validations:{},events:[event],ambiguity:{applied:false,message:null,simultaneous_conditions:[]}}]};
  const before=JSON.stringify(audit);
  const html=renderToStaticMarkup(React.createElement(PositionInspector,{audit,loading:false,error:null,onClose:()=>{}}));
  assert.match(html,/逐日策略時間軸/);assert.match(html,/首次停利觸發/);assert.match(html,/FIRST_TP_TRIGGERED/);assert.match(html,/技術詳細資訊/);
  assert.match(html,/當日收盤後完成的均線/);assert.equal(JSON.stringify(audit),before);
});
test("position-1 inspector distinguishes the reference MA, active stop, intraday trigger, and slipped execution",()=>{
  const {PositionInspector}=load("components/PositionInspector.tsx");
  const audit={backtest_id:"canonical-simple",ticker:"NVDA",strategy:"simple",position_id:"position-1",presentation:{ma_stop:{kind:"SIMPLE_FULL_STOP",percent_below_ma:1.5,multiplier:.985,formula:"MA(t-1) × 0.985"},sell_slippage_pct:.02,source:"DERIVED_FROM_STORED_AUDIT_AND_SAVED_REQUEST",persisted_audit_modified:false},position:{entry_date:"2021-10-14",entry_price:21.3726191123374,q0:4676,final_exit_date:"2021-12-03",final_return:.42897259563498466,net_pnl:42892.256092678974,gross_pnl:43013.701310303426,fees:121.4452176244414,holding_days:36,exit_final_close_reason:"MA_EXIT"},chart:{daily_data:[],executions:[{timestamp:"2021-12-03",side:"SELL",price:30.571443173565676,quantity:4676,gross_value:142952.0682795931,commission:71.47603413979655,slippage:28.59613288249743,position_remaining:0,event_type:"FINAL_EXIT",reason:"MA_EXIT"}]},timeline:[{date:"2021-12-03",timestamp:"2021-12-03",open:31.899227266863253,high:32.027822639120906,low:30.035115336865402,close:30.596343994140625,volume:544325600,previous_day_ma:31.043206787109376,current_day_ma:31.019,previous_day_atr:null,bias_sigma:null,current_quantity_at_open:4676,current_quantity_at_close:0,strategy_state_at_open:"LONG_NORMAL",strategy_state_at_close:"CLOSED",thresholds:{breakout_trigger:null,entry_level:null,day1_stop:null,simple_ma_exit_stop:30.577558685302737,ma_half_stop:null,break_day_low:null,first_tp_price:null,protective_stop:null,bias_extreme_threshold_price:null,atr_extreme_threshold_price:null},validations:{entry_day_volume:null,day2_confirmation:null},events:[{event:"MA_EXIT",source_event:"MA_EXIT",trigger_level:30.577558685302737,execution_price:30.571443173565676,shares_before:4676,shares_sold:4676,shares_remaining:0,state_before:"LONG_NORMAL",state_after:"CLOSED",metadata:{},stop_execution:{trigger_type:"INTRADAY_STOP",reference_ma:31.043206787109376,active_stop_price:30.577558685302737,open_price:31.899227266863253,low_price:30.035115336865402,raw_fill_price:30.577558685302737,actual_execution_price:30.571443173565676,sell_slippage_pct:.02,formula:"MA(t-1) × 0.985"}}],ambiguity:{applied:false,message:null,policy:null,chosen_path:null,simultaneous_conditions:[]}}]};
  const before=JSON.stringify(audit);
  const html=renderToStaticMarkup(React.createElement(PositionInspector,{audit,loading:false,error:null,onClose:()=>{}}));
  assert.match(html,/均線 −1.5% 停損出場/);
  assert.match(html,/盤中跌破停損線/);
  assert.match(html,/開盤仍高於停損線/);
  for(const value of ["$31.04","$30.58","$31.90","$30.04","$30.57","0.02%"]){assert.match(html,new RegExp(value.replace("$","\\$")));}
  assert.doesNotMatch(html,/跳空跌破停損線<\/span>/);
  assert.equal(JSON.stringify(audit),before);
});
test("mobile localization layout guards cover requested viewport breakpoints without browser use",()=>{
  const css=fs.readFileSync(path.join(root,"app/globals.css"),"utf8");
  for(const width of [375,390,430,768,1440]){
    if(width<=900)assert.match(css,/@media \(max-width: 900px\)/);
    if(width<=480)assert.match(css,/@media \(max-width: 480px\)/);
  }
  assert.match(css,/overflow-wrap:\s*anywhere/);assert.match(css,/\.technical-raw/);assert.match(css,/font-size:\s*16px/);
  assert.match(fs.readFileSync(path.join(root,"app/layout.tsx"),"utf8"),/lang="zh-TW"/);
});
