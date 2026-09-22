"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Download, LineChart, Play, Shield } from "lucide-react";
import { api, ApiClientError, MAAnalyticsAggregate, MAAnalyticsChart, MAAnalyticsEvent, MAAnalyticsRequest, MAAnalyticsStudy } from "@/lib/api";
import {
  buildAnalyticsBoundaryPath,
  buildAnalyticsDay2Marker,
  buildAnalyticsStopPath,
  MA_ANALYTICS_DAY2_STATUS_LABELS,
  MA_ANALYTICS_OBSERVATION_ORIGINS,
  MA_ANALYTICS_TARGET_TYPES,
  MA_ANALYTICS_TERMINAL_LABELS,
  prepareMaAnalyticsChart,
} from "@/lib/maAnalyticsChart.mjs";

const EMPTY_FORM: MAAnalyticsRequest = {
  ticker: "", selected_ma: 24, nearby_range: 5, step: 1,
  start_date: "2021-01-01", end_date: "2026-08-31",
  direction_mode: "LONG_SHORT_SPLIT", entanglement_mode: "ALL",
};

const fmtPct = (value: unknown) => value == null || !Number.isFinite(Number(value)) ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
const fmtNum = (value: unknown, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits);
const safeText = (value: unknown) => value == null ? "—" : String(value);

function Field({label,value,onChange,type="text"}:{label:string;value:string;onChange:(value:string)=>void;type?:string}) {
  return <label className="field"><span>{label}</span><input className="input" type={type} value={value} onChange={event=>onChange(event.target.value)}/></label>;
}
function NumberField({label,value,onChange,min=0,max=500}:{label:string;value:number;onChange:(value:number)=>void;min?:number;max?:number}) {
  return <label className="field"><span>{label}</span><input className="input" type="number" min={min} max={max} value={value} onChange={event=>onChange(Math.max(min,Math.min(max,Number(event.target.value)||min)))}/></label>;
}

function downloadFile(name:string, content:string, type:string) {
  const url=URL.createObjectURL(new Blob([content],{type}));
  const anchor=document.createElement("a"); anchor.href=url; anchor.download=name; anchor.click(); URL.revokeObjectURL(url);
}

function AnalyticsChart({chart,selectedEventId}:{chart:MAAnalyticsChart|null;selectedEventId:string|null}) {
  const [targetType,setTargetType]=useState("PCT_3");
  const [origin,setOrigin]=useState("POST_D1");
  const [condition,setCondition]=useState("BREAKOUT");
  useEffect(()=>{setTargetType("PCT_3");setOrigin("POST_D1");setCondition("BREAKOUT");},[selectedEventId]);
  const model=prepareMaAnalyticsChart(chart,selectedEventId,{targetType,origin,condition});
  const data=model.bars;
  const selected=model.selectedEvent as MAAnalyticsEvent|null;
  const failure=model.failure;
  const selectedTarget=model.selectedTarget;
  const selectedAudit=model.stopAudit;
  if(!data.length) return <div className="structure-chart-empty">選取 SMA 後會顯示後端提供的均線與事件資料。</div>;

  const width=1000, height=320, pad=22;
  const values:number[]=[];
  for(const item of data){
    values.push(item.low,item.high);
    if(item.sma!=null)values.push(item.sma);
    if(item.long_day1_threshold!=null)values.push(item.long_day1_threshold);
    if(item.short_day1_threshold!=null)values.push(item.short_day1_threshold);
    if(typeof item.box_high_at_session_start==="number")values.push(item.box_high_at_session_start);
    if(typeof item.box_low_at_session_start==="number")values.push(item.box_low_at_session_start);
  }
  for(const item of model.retestZoneHistory){values.push(item.retest_zone_low,item.retest_zone_high);}
  if(typeof selected?.reference_entry==="number")values.push(selected.reference_entry);
  if(typeof selectedTarget?.target_level==="number")values.push(selectedTarget.target_level);
  for(const item of selectedAudit){if(typeof item.stop_level==="number")values.push(item.stop_level);}
  const min=Math.min(...values), max=Math.max(...values), span=max-min||1;
  const x=(index:number)=>pad+(data.length<2?0:index*(width-2*pad)/(data.length-1));
  const y=(price:number)=>height-pad-(price-min)*(height-2*pad)/span;
  const idxByDate=new Map(data.map((item,index)=>[item.date,index]));
  const line=(key:"sma"|"long_day1_threshold"|"short_day1_threshold")=>data.map((item,index)=>item[key]==null?null:`${x(index)},${y(Number(item[key]))}`).filter(Boolean).join(" ");
  const bodyWidth=Math.max(1,Math.min(7,(width-2*pad)/data.length*0.58));
  const sessionWidth=data.length<2?width-2*pad:(width-2*pad)/(data.length-1);
  const target=typeof selectedTarget?.target_level==="number"?selectedTarget.target_level:null;
  const terminalDate=typeof failure?.terminal_date==="string"?failure.terminal_date:null;
  const sidewaysDates=Array.isArray(failure?.sideways_window_dates)?failure.sideways_window_dates as string[]:[];
  const retestZones=model.retestZoneHistory;
  const targetStart=typeof selectedTarget?.observation_start_date==="string"?idxByDate.get(selectedTarget.observation_start_date):undefined;
  const targetEndDate=typeof selectedTarget?.resolution_date==="string"?selectedTarget.resolution_date:data[data.length-1].date;
  const targetEnd=idxByDate.get(targetEndDate)??data.length-1;
  const referenceStart=selected?idxByDate.get(selected.d1_date):undefined;
  const targetLabel=target==null?null:`${selectedTarget?.target_type} · ${selectedTarget?.condition_type} · ${selectedTarget?.observation_origin}`;
  const terminalCode=typeof failure?.terminal_outcome==="string"?failure.terminal_outcome:null;
  const terminalLabel=terminalCode?(MA_ANALYTICS_TERMINAL_LABELS as Record<string,string>)[terminalCode]??"其他終態":null;
  const volumeFlags=selected?[
    selected.vol_ge_10?"≥10%":null,selected.vol_ge_20?"≥20%":null,selected.vol_ge_30?"≥30%":null,
  ].filter(Boolean):[];
  const boxHighPath=buildAnalyticsBoundaryPath(data,"box_high_at_session_start",x,y);
  const boxLowPath=buildAnalyticsBoundaryPath(data,"box_low_at_session_start",x,y);
  const stopPath=buildAnalyticsStopPath(selectedAudit,idxByDate,x,y);
  const selectedD2StatusLabel=selected
    ? (MA_ANALYTICS_DAY2_STATUS_LABELS as Record<string,string>)[selected.d2_status]??selected.d2_status
    : null;
  return <div className="structure-chart-shell overflow-x-auto">
    <div className="mb-3 flex flex-wrap gap-2 text-[10px]">
      <label className="field min-w-32"><span>目標</span><select className="input" value={targetType} onChange={event=>setTargetType(event.target.value)}>{MA_ANALYTICS_TARGET_TYPES.map(type=><option key={type} value={type}>{type==="PCT_3"?"+3%":type.replace("ATR_","ATR ")}</option>)}</select></label>
      <label className="field min-w-36"><span>觀察起點</span><select className="input" value={origin} onChange={event=>setOrigin(event.target.value)}>{MA_ANALYTICS_OBSERVATION_ORIGINS.map(value=><option key={value} value={value}>{value==="POST_D1"?"D1 條件後／D2 開盤":"Day2 成功後／D3 開盤"}</option>)}</select></label>
      <label className="field min-w-52"><span>條件</span><select className="input" value={condition} onChange={event=>setCondition(event.target.value)}>{[
        "BREAKOUT","VOL_LT_10","VOL_GE_10","VOL_GE_20","VOL_GE_30","DAY2_SUCCESS",
        "DAY2_SUCCESS_AND_VOL_GE_10","DAY2_SUCCESS_AND_VOL_GE_20","DAY2_SUCCESS_AND_VOL_GE_30",
      ].map(value=><option key={value} value={value}>{value}</option>)}</select></label>
    </div>
    <svg viewBox={`0 0 ${width} ${height}`} className="min-w-[760px] w-full" role="img" aria-label={`SMA${chart?.period} MA Breakout Analytics chart`}>
      <rect x="0" y="0" width={width} height={height} fill="#0b131e"/>
      {data.map((bar,index)=>{
        const eventDay=bar.event_ids.length>0;
        const day2Marker=buildAnalyticsDay2Marker(bar,selected);
        const day2Color=day2Marker?.status==="SUCCESS"?"#34d399":day2Marker?.status==="FAILURE"?"#fb7185":"#c4b5fd";
        const boxHigh=bar.box_high_at_session_start;
        const boxLow=bar.box_low_at_session_start;
        const activeBox=bar.box_active_at_session_start&&typeof boxHigh==="number"&&typeof boxLow==="number";
        const sessionLeft=Math.max(pad,x(index)-sessionWidth/2);
        const sessionRight=Math.min(width-pad,x(index)+sessionWidth/2);
        const selectedD1=selected?.d1_date===bar.date;
        const yOpen=y(bar.open), yClose=y(bar.close), rising=bar.close>=bar.open;
        const volumePct=selectedD1&&selected?.volume_change!=null?`${(selected.volume_change*100).toFixed(2)}%`:"—";
        return <g key={bar.date}>
          {activeBox&&<rect x={sessionLeft} y={y(boxHigh!)} width={Math.max(0,sessionRight-sessionLeft)} height={Math.max(0,y(boxLow!)-y(boxHigh!))} fill="#22d3ee" opacity="0.11"/>}
          {sidewaysDates.includes(bar.date)&&<rect x={x(index)-bodyWidth/2} y={pad} width={bodyWidth} height={height-2*pad} fill="#a78bfa" opacity="0.09"/>}
          {retestZones.filter(zone=>zone.date===bar.date).map(zone=><rect key={`retest-${bar.date}`} x={x(index)-bodyWidth/2} y={y(zone.retest_zone_high)} width={bodyWidth} height={Math.max(1,y(zone.retest_zone_low)-y(zone.retest_zone_high))} fill={zone.intersects?"#fbbf24":"#f59e0b"} opacity={zone.intersects?0.22:0.09}><title>{`後端回測區 ${zone.retest_zone_low.toFixed(3)}–${zone.retest_zone_high.toFixed(3)} · ${zone.intersects?"K棒區間相交":"未相交"}`}</title></rect>)}
          <line x1={x(index)} x2={x(index)} y1={y(bar.high)} y2={y(bar.low)} stroke={rising?"#34d399":"#fb7185"} strokeWidth="1"/>
          <rect x={x(index)-bodyWidth/2} y={Math.min(yOpen,yClose)} width={bodyWidth} height={Math.max(1,Math.abs(yClose-yOpen))} fill={rising?"#34d399":"#fb7185"} opacity="0.9"/>
          {eventDay&&<circle data-marker-type="DAY1" cx={x(index)} cy={y(bar.close)} r={selectedD1?5:3} fill={selectedD1?"#fbbf24":"#22d3ee"} stroke="#071019" strokeWidth="1"><title>{selectedD1?`D1 ${bar.date} · ${selected?.direction} · Volume ${volumePct} · ${volumeFlags.join(" / ")||"無 nested 門檻"}`:`D1 event ${bar.date} · ${bar.event_ids.length} event(s)`}</title></circle>}
          {day2Marker&&<g data-marker-type="DAY2" data-event-id={day2Marker.eventId} data-day2-status={day2Marker.status}>
            <path d={`M ${x(index)} ${yClose-8} L ${x(index)+5} ${yClose-3} L ${x(index)} ${yClose+2} L ${x(index)-5} ${yClose-3} Z`} fill={day2Color} stroke="#071019" strokeWidth="1"/>
            <text x={x(index)+7} y={yClose-4} fill={day2Color} fontSize="9">D2 {day2Marker.label}</text>
            <title>{`D2 ${bar.date} · ${day2Marker.label} · backend status=${day2Marker.status}`}</title>
          </g>}
          {bar.box_formed_on_close&&<path d={`M ${x(index)-4} ${y(bar.close)-8} L ${x(index)+4} ${y(bar.close)-8} L ${x(index)} ${y(bar.close)-2} Z`} fill="#22d3ee"><title>本日收盤確認 entanglement；箱體自下一交易日生效</title></path>}
          {terminalDate===bar.date&&<path d={`M ${x(index)-5} ${pad+2} L ${x(index)+5} ${pad+2} L ${x(index)} ${pad+10} Z`} fill="#fbbf24"><title>{`${terminalCode} · ${terminalLabel}`}</title></path>}
          {sidewaysDates.includes(bar.date)&&<rect x={x(index)-bodyWidth/2} y={height-17} width={bodyWidth} height="5" fill="#a78bfa"><title>{`Sideways window ${String(failure?.sideways_window_start??"")} → ${String(failure?.sideways_window_end??"")}`}</title></rect>}
        </g>;
      })}
      <polyline points={line("sma")} fill="none" stroke="#fbbf24" strokeWidth="1.7"/>
      <polyline points={line("long_day1_threshold")} fill="none" stroke="#34d399" strokeWidth="0.8" strokeDasharray="4 4" opacity="0.7"/>
      <polyline points={line("short_day1_threshold")} fill="none" stroke="#fb7185" strokeWidth="0.8" strokeDasharray="4 4" opacity="0.7"/>
      <path d={boxHighPath} fill="none" stroke="#22d3ee" strokeWidth="1.2"/>
      <path d={boxLowPath} fill="none" stroke="#67e8f9" strokeWidth="1.2" strokeDasharray="3 2"/>
      {typeof selected?.reference_entry==="number"&&referenceStart!=null&&<line x1={x(referenceStart)} x2={width-pad} y1={y(selected.reference_entry)} y2={y(selected.reference_entry)} stroke="#c4b5fd" strokeDasharray="2 4" strokeWidth="1.1"><title>{`Reference Entry ${selected.reference_entry}`}</title></line>}
      {target!=null&&targetStart!=null&&<line x1={x(targetStart)} x2={x(targetEnd)} y1={y(target)} y2={y(target)} stroke="#22d3ee" strokeDasharray="5 4" strokeWidth="1.4"><title>{`後端 target ${target} · ${targetLabel}`}</title></line>}
      {stopPath&&<path d={stopPath} data-stop-audit-origin={origin} data-stop-audit-condition={condition} data-stop-audit-target={targetType} fill="none" stroke="#fb7185" strokeWidth="1.3"><title>{`後端 ${targetType} / ${condition} / ${origin} dynamic stop audit`}</title></path>}
    </svg>
    <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-400"><span><i className="mr-1 inline-block h-2 w-2 bg-amber-300"/>完成 SMA</span><span><i className="mr-1 inline-block h-2 w-2 bg-violet-300"/>Reference Entry</span><span><i className="mr-1 inline-block h-2 w-2 bg-cyan-300"/>所選 target</span><span><i className="mr-1 inline-block h-2 w-2 bg-rose-400"/>所選條件／origin dynamic stop</span><span>青色階梯與淡底：session-start BoxHigh/Low</span><span>黃色帶：後端 ±0.1% retest zone</span><span>紫色底：Sideways confirmation window</span><span>青色三角：收盤確認糾結，次日生效</span></div>
    {selected&&<div className="mt-3 grid gap-2 rounded border border-[#27384d] bg-[#0a111b] p-3 text-[10px] text-slate-300 sm:grid-cols-2 lg:grid-cols-4">
      <span>D1 {selected.d1_date} · {selected.direction}</span><span data-day2-status={selected.d2_status} title={`Backend Day2 status: ${selected.d2_status}`}>D2 {selectedD2StatusLabel} · {selected.d2_status} · {selected.d2_date??"—"}</span>
      <span>Reference Entry {fmtNum(selected.reference_entry)}</span>
      <span>D1 Volume {selected.volume_evaluable?fmtPct(selected.volume_change):"N/E"}</span><span>Nested volume {volumeFlags.join(" / ")||"未達 ≥10%"}</span>
      <span>Target {selectedTarget?`${selectedTarget.target_type} · ${fmtNum(selectedTarget.target_level)}`:"此條件／origin 無 outcome"}</span>
      <span>Origin {origin} · {selectedTarget?.observation_start_date??"尚無觀察起點"}</span>
      <span>Terminal {terminalCode?`${terminalCode} · ${terminalLabel}`:"—"}</span>
      {terminalCode==="SIDEWAYS"&&<span>Sideways {failure?.sideways_window_bars??"—"} bars · {String(failure?.sideways_window_start??"—")} → {String(failure?.sideways_window_end??"—")} · range/ATR {fmtNum(failure?.sideways_range_atr)}</span>}
      {failure?.sideways_window_high!=null&&<span>Sideways High/Low {fmtNum(failure.sideways_window_high)} / {fmtNum(failure.sideways_window_low)} · ATR14 {fmtNum(failure.sideways_atr14)} · threshold {fmtNum(failure.sideways_threshold_atr)} ATR</span>}
      {failure?.sideways_atr_reference_date&&<span>Sideways ATR snapshot {failure.sideways_atr_reference_date}</span>}
      <span>Retest audit bars {retestZones.length} · intersects {retestZones.filter(zone=>zone.intersects).length}</span>
      <span>Entanglement {selected.entanglement_cohort} · box {selected.entanglement_box_id??"—"}</span>
    </div>}
  </div>;
}

function Stat({label,value}:{label:string;value:string}){return <div className="rounded border border-[#27384d] bg-[#0a111b] p-3"><p className="m-0 text-[10px] text-slate-500">{label}</p><p className="mb-0 mt-1 text-sm font-semibold text-slate-100">{value}</p></div>;}

export function MaBreakoutAnalyticsStudy(){
  const [form,setForm]=useState(EMPTY_FORM);
  const [study,setStudy]=useState<MAAnalyticsStudy|null>(null);
  const [summary,setSummary]=useState<Record<string,unknown>|null>(null);
  const [events,setEvents]=useState<MAAnalyticsEvent[]>([]);
  const [chart,setChart]=useState<MAAnalyticsChart|null>(null);
  const [selectedPeriod,setSelectedPeriod]=useState(24);
  const [selectedEventId,setSelectedEventId]=useState<string|null>(null);
  const [eventDetail,setEventDetail]=useState<Record<string,unknown>|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);

  async function loadPeriod(id:string,period:number){
    setSelectedPeriod(period);
    try{const [eventResult,chartResult]=await Promise.all([api.maBreakoutAnalyticsEvents(id,period),api.maBreakoutAnalyticsChart(id,period)]);setEvents(eventResult.events);setChart(chartResult);setSelectedEventId(null);setEventDetail(null);}
    catch(reason){setError(reason instanceof ApiClientError?reason.details.message:reason instanceof Error?reason.message:"無法載入圖表資料");}
  }
  useEffect(()=>{if(study)void loadPeriod(study.study_id,selectedPeriod);},[study?.study_id,selectedPeriod]);

  async function run(){
    if(busy||!form.ticker.trim())return;
    setBusy(true);setError(null);setStudy(null);setSummary(null);setEvents([]);setChart(null);setSelectedEventId(null);
    try{
      const created=await api.createMaBreakoutAnalyticsStudy({...form,ticker:form.ticker.trim().toUpperCase()});
      const [summaryResult,eventResult,chartResult]=await Promise.all([
        api.maBreakoutAnalyticsSummary(created.study_id),
        api.maBreakoutAnalyticsEvents(created.study_id,created.config.selected_ma),
        api.maBreakoutAnalyticsChart(created.study_id,created.config.selected_ma),
      ]);
      setStudy(created);setSummary(summaryResult);setEvents(eventResult.events);setChart(chartResult);setSelectedPeriod(created.config.selected_ma);
    }catch(reason){setError(reason instanceof ApiClientError?reason.details.message:reason instanceof Error?reason.message:"研究無法完成");}
    finally{setBusy(false);}
  }

  async function selectEvent(event:MAAnalyticsEvent){
    if(!study)return;
    setSelectedEventId(event.event_id);
    try{setEventDetail(await api.maBreakoutAnalyticsEvent(study.study_id,event.event_id));}
    catch(reason){setError(reason instanceof ApiClientError?reason.details.message:reason instanceof Error?reason.message:"無法載入事件細節");}
  }

  const aggregates=(summary?.aggregates??[]) as MAAnalyticsAggregate[];
  const periodAggregates=useMemo(()=>aggregates.filter(row=>row.period===selectedPeriod),[aggregates,selectedPeriod]);
  const probabilityRows=periodAggregates.filter(row=>row.aggregate_type==="PROBABILITY");
  const targetRows=periodAggregates.filter(row=>row.aggregate_type==="TARGET");
  const failureRows=periodAggregates.filter(row=>row.aggregate_type==="FAILURE_PATH");
  const selectedSummaries=((summary?.period_summary as Array<Record<string,unknown>>|undefined)??[]).filter(row=>row.period===selectedPeriod);
  const day2ProbabilityByDirection=new Map(probabilityRows.filter(row=>row.condition_type==="DAY2_SUCCESS").map(row=>[row.direction,row.probability]));
  const day2ProbabilityLabel=form.direction_mode==="LONG_SHORT_SPLIT"
    ? `Long ${fmtPct(day2ProbabilityByDirection.get("LONG"))} / Short ${fmtPct(day2ProbabilityByDirection.get("SHORT"))}`
    : fmtPct(day2ProbabilityByDirection.get(form.direction_mode==="SHORT_ONLY"?"SHORT":"LONG"));
  const totalEventCount=selectedSummaries.reduce((total,row)=>total+Number(row.event_count??0),0);
  const totalDay2Evaluable=selectedSummaries.reduce((total,row)=>total+Number(row.day2_evaluable??0),0);
  const totalFailureEvents=selectedSummaries.reduce((total,row)=>total+Number(row.day2_failure_events??0),0);

  async function exportFile(format:"json"|"events.csv"|"aggregates.csv"){
    if(!study)return;
    try{const body=await api.exportMaBreakoutAnalytics(study.study_id,format);downloadFile(`${study.ticker}_MA_BREAKOUT_ANALYTICS.${format==="json"?"json":"csv"}`,typeof body==="string"?body:JSON.stringify(body,null,2),format==="json"?"application/json":"text/csv;charset=utf-8");}
    catch(reason){setError(reason instanceof ApiClientError?reason.details.message:reason instanceof Error?reason.message:"匯出失敗");}
  }

  return <main className="min-h-screen p-3 sm:p-5">
    <header className="mx-auto mb-4 flex max-w-[1500px] flex-wrap items-center justify-between gap-3 border-b border-[#223247] pb-4">
      <div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-lg border border-violet-400/30 bg-violet-400/10 text-violet-300"><LineChart size={20}/></div><div><h1 className="m-0 text-lg font-semibold">MA_BREAKOUT_ANALYTICS_V1</h1><p className="m-0 text-[11px] text-slate-500">均線突破事件與條件機率研究 · 不下單、不建立投資組合</p></div></div>
      <div className="flex gap-2"><Link href="/" className="inline-flex items-center gap-2 rounded-md border border-[#293a50] px-3 py-2 text-xs font-semibold text-slate-300"><ArrowLeft size={14}/>回到回測</Link><Link href="/ma-box" className="inline-flex items-center gap-2 rounded-md border border-cyan-400/25 px-3 py-2 text-xs font-semibold text-cyan-200">MA_BOX_LONG_V1</Link></div>
    </header>
    <div className="mx-auto grid max-w-[1500px] gap-4">
      <section className="panel p-4"><div className="mb-3 flex items-center gap-2"><Play size={16} className="text-violet-300"/><h2 className="m-0 text-sm">研究設定</h2></div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Ticker" value={form.ticker} onChange={ticker=>setForm({...form,ticker:ticker.toUpperCase()})}/>
          <NumberField label="選定 SMA" value={form.selected_ma} onChange={selected_ma=>setForm({...form,selected_ma})} min={2}/>
          <NumberField label="附近範圍 ±" value={form.nearby_range} onChange={nearby_range=>setForm({...form,nearby_range})}/>
          <NumberField label="Step" value={form.step} onChange={step=>setForm({...form,step})} min={1}/>
          <Field label="開始日期" type="date" value={form.start_date} onChange={start_date=>setForm({...form,start_date})}/>
          <Field label="結束日期" type="date" value={form.end_date} onChange={end_date=>setForm({...form,end_date})}/>
          <label className="field"><span>方向</span><select className="input" value={form.direction_mode} onChange={event=>setForm({...form,direction_mode:event.target.value as MAAnalyticsRequest["direction_mode"]})}><option value="LONG_SHORT_SPLIT">多空分開</option><option value="LONG_ONLY">只看多頭</option><option value="SHORT_ONLY">只看空頭</option></select></label>
          <label className="field"><span>Entanglement cohort</span><select className="input" value={form.entanglement_mode} onChange={event=>setForm({...form,entanglement_mode:event.target.value as MAAnalyticsRequest["entanglement_mode"]})}><option value="ALL">全部</option><option value="EXCLUDE_ENTANGLED">排除糾結</option><option value="ONLY_ENTANGLED">只看糾結</option><option value="SPLIT_ENTANGLED_CLEAN">糾結／乾淨分開</option></select></label>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3"><button onClick={run} disabled={busy||!form.ticker.trim()} className="min-h-11 rounded-lg bg-violet-300 px-5 text-sm font-extrabold text-slate-950 disabled:opacity-50">{busy?"正在分析…":"開始事件分析"}</button><span className="text-[11px] text-slate-500">D1 breakout 用完成 SMA ±0.2%；統計基準價不是實際成交；不會自動挑選 SMA。</span></div>
        {error&&<p className="mb-0 mt-3 rounded border border-rose-400/30 bg-rose-400/10 p-3 text-xs text-rose-200">{error}</p>}
      </section>
      {!study&&!busy&&<section className="panel grid min-h-60 place-items-center p-8 text-center"><div><Shield className="mx-auto text-violet-300" size={32}/><h2 className="mt-3 text-base">只做事件與條件機率分析</h2><p className="mb-0 mt-2 max-w-xl text-xs leading-5 text-slate-500">比較 Day2 成立、量能條件、目標先於動態 stop，以及 Day2 failure 後的第一個因果終態。這裡不建立交易、資金曲線或 MA 排名。</p></div></section>}
      {busy&&<div className="panel p-5 text-sm text-violet-200">正在讀取日線暖機資料並計算事件…</div>}
      {study&&summary&&<>
        <section className="rounded-xl border border-violet-400/25 bg-violet-400/5 p-4 text-xs text-violet-100/85"><strong>事件研究，不是交易策略</strong><p className="mb-0 mt-1">Reference entry：{study.reference_entry_label}。目標與 stop 僅作條件統計，不產生部位或投資組合。</p><div className="mt-3 grid gap-2 text-[10px] text-slate-400 sm:grid-cols-4"><span>資料：{study.data_provenance?.data_start as string} → {study.data_provenance?.data_end as string}</span><span>分析期間：{study.evaluation_start} → {study.evaluation_end}</span><span>來源：{study.provider}</span><span className="break-all">Fingerprint：{study.data_fingerprint}</span></div><p className="mb-0 mt-2 break-all text-[9px] text-slate-500">Spec Rev {study.spec_revision_number} · {study.spec_hash}</p></section>
        <section className="panel overflow-hidden"><header className="flex flex-wrap items-center justify-between gap-2 border-b border-[#223247] px-4 py-3"><div><h2 className="m-0 text-sm">附近均線週期</h2><p className="m-0 text-[10px] text-slate-500">只比較事件統計，不排名、不推薦最佳 MA</p></div><div className="flex flex-wrap gap-1">{study.periods.map(period=><button key={period} onClick={()=>void loadPeriod(study.study_id,period)} className={`min-h-9 min-w-9 rounded border px-2 text-xs font-semibold ${selectedPeriod===period?"border-violet-300 bg-violet-400/15 text-violet-200":"border-[#293a50] text-slate-400"}`}>SMA{period}</button>)}</div><div className="flex flex-wrap gap-2"><button onClick={()=>void exportFile("json")} className="inline-flex min-h-8 items-center gap-1 rounded border border-violet-400/25 px-2 text-[10px] text-violet-200"><Download size={12}/>JSON</button><button onClick={()=>void exportFile("events.csv")} className="inline-flex min-h-8 items-center gap-1 rounded border border-violet-400/25 px-2 text-[10px] text-violet-200">Event CSV</button><button onClick={()=>void exportFile("aggregates.csv")} className="inline-flex min-h-8 items-center gap-1 rounded border border-violet-400/25 px-2 text-[10px] text-violet-200">Aggregate CSV</button></div></header>
          <div className="grid gap-2 p-4 sm:grid-cols-4"><Stat label="SMA breakout events" value={safeText(totalEventCount)}/><Stat label="Day2 evaluable" value={safeText(totalDay2Evaluable)}/><Stat label="Day2 success" value={day2ProbabilityLabel}/><Stat label="Day2 failure paths" value={safeText(totalFailureEvents)}/></div>
        </section>
        <section className="panel overflow-hidden"><header className="border-b border-[#223247] px-4 py-3"><h2 className="m-0 text-sm">Breakout／量能／Day2 條件</h2><p className="m-0 mt-1 text-[10px] text-slate-500">量能門檻為 nested conditions；Wilson 95% 區間及低樣本標記隨 aggregate 保存，多空分母分列。</p></header><div className="overflow-x-auto"><table className="table"><thead><tr><th>方向</th><th>條件</th><th>N</th><th>成功數</th><th>機率</th><th>Wilson 95%</th><th>樣本</th></tr></thead><tbody>{probabilityRows.map(row=><tr key={row.aggregate_id}><td>{row.direction}</td><td>{row.condition_type}</td><td>{row.eligible_count}</td><td>{row.success_count}</td><td>{fmtPct(row.probability)}</td><td>{fmtPct(row.wilson_lower)} – {fmtPct(row.wilson_upper)}</td><td>{row.low_sample_size?"LOW_SAMPLE_SIZE":"—"}</td></tr>)}</tbody></table></div></section>
        <section className="panel overflow-hidden"><header className="border-b border-[#223247] px-4 py-3"><h2 className="m-0 text-sm">Target-before-stop</h2><p className="m-0 mt-1 text-[10px] text-slate-500">POST_D1 從 D2 開始；Day2-conditioned POST_D2_SUCCESS 從 D3 開始。右設限不納入 resolved 分母。</p></header><div className="overflow-x-auto"><table className="table"><thead><tr><th>方向</th><th>條件</th><th>Target</th><th>Origin</th><th>Eligible</th><th>Resolved</th><th>Target first</th><th>機率</th><th>Wilson 95%</th><th>Censored</th></tr></thead><tbody>{targetRows.map(row=><tr key={row.aggregate_id}><td>{row.direction}</td><td>{row.condition_type}</td><td>{row.target_type}</td><td>{row.observation_origin}</td><td>{row.eligible_count}</td><td>{row.resolved_count}</td><td>{row.success_count}</td><td>{fmtPct(row.probability)}</td><td>{fmtPct(row.wilson_lower)} – {fmtPct(row.wilson_upper)}</td><td>{row.censored_count}</td></tr>)}</tbody></table>{!targetRows.length&&<p className="p-4 text-xs text-slate-500">此週期目前沒有可列示的目標 aggregate。</p>}</div></section>
        <section className="panel overflow-hidden"><header className="border-b border-[#223247] px-4 py-3"><h2 className="m-0 text-sm">Day2 failure 的第一個終態</h2><p className="m-0 mt-1 text-[10px] text-slate-500">Sideways 使用獨立的四根完成 K 棒／ATR14 價格整理定義，不等同 MA entanglement。</p></header><div className="overflow-x-auto"><table className="table"><thead><tr><th>方向</th><th>Volume condition</th><th>N</th><th>Resolved</th><th>Retest</th><th>Return</th><th>Sideways</th><th>三者合計</th><th>Trend away</th><th>Censored</th></tr></thead><tbody>{failureRows.map(row=><tr key={row.aggregate_id}><td>{row.direction}</td><td>{row.condition_type}</td><td>{row.eligible_count}</td><td>{row.resolved_count}</td><td>{safeText((row.terminal_counts as Record<string,number>|undefined)?.MA_RETEST_REBOUND)} / {safeText((row.terminal_counts as Record<string,number>|undefined)?.MA_RETEST_REJECTION)}</td><td>{safeText((row.terminal_counts as Record<string,number>|undefined)?.RETURN_TO_BEAR)} / {safeText((row.terminal_counts as Record<string,number>|undefined)?.RETURN_TO_BULL)}</td><td>{safeText((row.terminal_counts as Record<string,number>|undefined)?.SIDEWAYS)}</td><td>{fmtPct(row.combined_probability)}</td><td>{fmtPct(row.trend_probability)}</td><td>{row.censored_count}</td></tr>)}</tbody></table>{!failureRows.length&&<p className="p-4 text-xs text-slate-500">目前沒有 Day2 failure event。</p>}</div></section>
        <section className="panel p-4"><header className="mb-3"><h2 className="m-0 text-sm">後端提供的 K 線與事件 overlay</h2><p className="m-0 mt-1 text-[10px] text-slate-500">圖形只呈現後端 daily data、閾值、target、stop audit 與狀態，不在前端重新判定事件。</p></header><AnalyticsChart chart={chart} selectedEventId={selectedEventId}/></section>
        <section className="grid gap-4 lg:grid-cols-[1.2fr_.8fr]"><div className="panel overflow-hidden"><header className="border-b border-[#223247] px-4 py-3"><h2 className="m-0 text-sm">SMA{selectedPeriod} Day1 events</h2><p className="m-0 mt-1 text-[10px] text-slate-500">選取事件以檢視 D1/D2、reference entry、volume 與 target / terminal audit。</p></header><div className="max-h-[460px] overflow-auto"><table className="table"><thead><tr><th>Date</th><th>Side</th><th>D1 close</th><th>D2</th><th>Volume</th><th>Cohort</th></tr></thead><tbody>{events.map(event=><tr key={event.event_id} onClick={()=>void selectEvent(event)} className={`cursor-pointer ${selectedEventId===event.event_id?"bg-violet-400/10":""}`}><td>{event.d1_date}</td><td>{event.direction}</td><td>{fmtNum(event.d1_close)}</td><td>{event.d2_status}</td><td>{event.volume_evaluable?fmtPct(event.volume_change):"N/E"}</td><td>{event.entanglement_cohort}</td></tr>)}</tbody></table>{!events.length&&<p className="p-4 text-xs text-slate-500">此週期沒有符合的 Day1 breakout。</p>}</div></div>
          <div className="panel p-4"><h2 className="m-0 text-sm">事件明細</h2>{!eventDetail?<p className="text-xs text-slate-500">選一筆事件查看完整 D1／D2 結果。</p>:<pre className="technical-raw mt-3">{JSON.stringify(eventDetail,null,2)}</pre>}</div></section>
      </>}
    </div>
  </main>;
}
