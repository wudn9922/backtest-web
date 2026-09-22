"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, Download, LineChart, Play, Shield } from "lucide-react";
import { api, ApiClientError, MABoxRequest, MABoxRun, MABoxStudy } from "@/lib/api";
import { buildStepBoundaryPath } from "@/lib/chartBoundary.mjs";
import { focusWindow, panViewport, resetZoom, zoomIn, zoomOut } from "@/lib/chartViewport.mjs";

const DEFAULT_FORM: MABoxRequest = {
  ticker: "SMCI", selected_ma: 24, nearby_range: 5, step: 1,
  start_date: "2021-01-01", end_date: "2026-09-01",
};

function pct(value: unknown, digits = 2) {
  const n = Number(value); return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : "—";
}
function money(value: unknown) {
  const n = Number(value); return Number.isFinite(n) ? n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }) : "—";
}
function metric(run: MABoxRun | undefined, key: string) { return run?.summary?.[key]; }
function downloadJson(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:"application/json"}));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click(); URL.revokeObjectURL(url);
}
function downloadTradesCsv(name: string, rows: Array<Record<string, unknown>>) {
  const fields = ["position_id", "entry_date", "entry_price", "final_exit_date", "exit_final_close_reason", "q0", "gross_pnl", "net_pnl", "return_pct", "holding_days"];
  const quote = (value: unknown) => `"${String(value ?? "").replaceAll("\"", "\"\"")}"`;
  const text = [fields.join(","), ...rows.map(row => fields.map(field => quote(row[field])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([text], {type:"text/csv;charset=utf-8"}));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click(); URL.revokeObjectURL(url);
}

export function MaBoxStudy() {
  const [form, setForm] = useState<MABoxRequest>(DEFAULT_FORM);
  const [study, setStudy] = useState<MABoxStudy | null>(null);
  const [period, setPeriod] = useState(DEFAULT_FORM.selected_ma);
  const [focusTrade, setFocusTrade] = useState<{entry?:string;exit?:string}|null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const next = await api.createMaBoxStudy(form);
      setStudy(next); setPeriod(next.selected_ma);
    } catch (reason) {
      setError(reason instanceof ApiClientError ? reason.details.message : reason instanceof Error ? reason.message : "研究無法完成");
    } finally { setBusy(false); }
  }

  const active = study?.runs[String(period)]?.MA_BOX_LONG_V1;
  const baseline = study?.runs[String(period)]?.MA_LONG_BASELINE;
  const bh = study?.buy_and_hold;

  return <main className="min-h-screen p-3 sm:p-5">
    <header className="mx-auto mb-4 flex max-w-[1500px] flex-wrap items-center justify-between gap-3 border-b border-[#223247] pb-4">
      <div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-lg border border-cyan-400/30 bg-cyan-400/10 text-cyan-300"><LineChart size={20}/></div><div><h1 className="m-0 text-lg font-semibold">MA_BOX_LONG_V1</h1><p className="m-0 text-[11px] text-slate-500">選定均線長期策略比較 · 研究頁面</p></div></div>
      <div className="flex gap-2"><Link href="/" className="inline-flex items-center gap-2 rounded-md border border-[#293a50] px-3 py-2 text-xs font-semibold text-slate-300"><ArrowLeft size={14}/>正式回測</Link><Link href="/research" className="inline-flex items-center gap-2 rounded-md border border-violet-400/25 px-3 py-2 text-xs font-semibold text-violet-200"><Shield size={14}/>研究框架</Link></div>
    </header>
    <div className="mx-auto grid max-w-[1500px] gap-4">
      <section className="panel p-4"><div className="mb-3 flex items-center gap-2"><Play size={16} className="text-cyan-300"/><h2 className="m-0 text-sm">均線箱型長期比較</h2></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <Field label="標的" value={form.ticker} onChange={value=>setForm({...form,ticker:value.toUpperCase()})}/>
        <NumberField label="選定 SMA" value={form.selected_ma} onChange={value=>setForm({...form,selected_ma:value})}/>
        <NumberField label="附近範圍 ±" value={form.nearby_range} onChange={value=>setForm({...form,nearby_range:value})}/>
        <NumberField label="步進" value={form.step} onChange={value=>setForm({...form,step:value})}/>
        <Field label="開始日期" type="date" value={form.start_date} onChange={value=>setForm({...form,start_date:value})}/>
        <Field label="結束日期" type="date" value={form.end_date} onChange={value=>setForm({...form,end_date:value})}/>
      </div><div className="mt-3 flex flex-wrap items-center gap-3"><button onClick={run} disabled={busy} className="min-h-11 rounded-lg bg-cyan-400 px-5 text-sm font-extrabold text-slate-950 disabled:opacity-50">{busy?"正在執行…":"開始比較"}</button><span className="text-[11px] text-slate-500">固定：SMA、OHLC Heuristic、MA−1.5% 停損、無固定停利。此頁不會自動選出最佳均線。</span></div>{error&&<p className="mb-0 mt-3 rounded border border-rose-400/30 bg-rose-400/10 p-3 text-xs text-rose-200">{error}</p>}</section>
      {!study && !busy && <section className="panel grid min-h-72 place-items-center p-8 text-center"><div><LineChart className="mx-auto text-cyan-300" size={32}/><h2 className="mt-3 text-base">選擇均線後開始研究</h2><p className="mb-0 mt-2 max-w-xl text-xs leading-5 text-slate-500">比較 MA_LONG_BASELINE、MA_BOX_LONG_V1 與 BUY_AND_HOLD。每個附近 SMA 都有獨立的箱型狀態與完整 audit。</p></div></section>}
      {busy && <div className="panel p-5 text-sm text-cyan-200">正在準備資料、執行附近均線並保存 audit…</div>}
      {study && <>
        <section className="rounded-xl border border-amber-400/25 bg-amber-400/5 p-4 text-xs text-amber-100/85"><div className="flex gap-2"><Shield size={16} className="shrink-0 text-amber-300"/><div><strong>研究策略，不是正式策略</strong><p className="mb-0 mt-1">MA_BOX_LONG_V1 使用獨立 revision；Simple、Advanced 與 Advanced + Day1Stop 未被修改。這裡只做選定均線與附近週期的比較。</p></div></div><div className="mt-3 grid gap-2 text-[10px] text-slate-400 sm:grid-cols-4"><span>資料：{study.data_provenance.data_start} → {study.data_provenance.data_end}</span><span>公平起點：{study.evaluation_start}</span><span>資料來源：{study.data_provenance.provider}</span><span className="break-all">資料指紋：{study.data_provenance.fingerprint ?? "—"}</span></div></section>
        <section className="panel overflow-hidden"><header className="flex flex-wrap items-center justify-between gap-2 border-b border-[#223247] px-4 py-3"><div><h2 className="m-0 text-sm">附近 SMA 比較</h2><p className="m-0 text-[10px] text-slate-500">每個 period 獨立執行；選定 SMA 僅作視覺突出</p></div><div className="flex flex-wrap gap-1">{study.periods.map(p=><button key={p} onClick={()=>setPeriod(p)} className={`min-h-9 min-w-9 rounded border px-2 text-xs font-semibold ${period===p?"border-cyan-300 bg-cyan-400/15 text-cyan-200":"border-[#293a50] text-slate-400"}`}>{p}</button>)}</div></header><div className="overflow-x-auto"><table className="table"><thead><tr><th>SMA</th><th>Baseline 報酬</th><th>Box 報酬</th><th>Box MDD</th><th>Calmar</th><th>交易筆數</th><th>Exposure</th></tr></thead><tbody>{study.periods.map(p=>{const b=study.runs[String(p)]?.MA_LONG_BASELINE;const x=study.runs[String(p)]?.MA_BOX_LONG_V1;return <tr key={p} className={p===study.selected_ma?"bg-cyan-400/5":""}><td className="font-bold">SMA{p}{p===study.selected_ma&&<span className="ml-1 text-cyan-300">（選定）</span>}</td><td>{pct(metric(b,"total_return"))}</td><td>{pct(metric(x,"total_return"))}</td><td className="text-rose-300">{pct(metric(x,"max_drawdown"))}</td><td>{metric(x,"calmar_ratio") == null ? "—" : Number(metric(x,"calmar_ratio")).toFixed(2)}</td><td>{String(metric(x,"number_of_positions") ?? "—")}</td><td>{metric(x,"exposure_pct") == null ? "—" : `${Number(metric(x,"exposure_pct")).toFixed(1)}%`}</td></tr>})}</tbody></table></div></section>
        {study.local_robustness&&<section className="panel p-4"><h2 className="m-0 text-sm">附近範圍穩定性摘要</h2><p className="mb-0 mt-1 text-[10px] text-slate-500">僅呈現比較範圍的中位數／最小值／最大值，不排序、不自動選擇均線。</p><div className="mt-3 grid gap-2 sm:grid-cols-4">{["total_return","cagr","max_drawdown","calmar_ratio"].map(key=>{const item=study.local_robustness?.metrics[key];return <div key={key} className="rounded border border-[#27384d] bg-[#0a111b] p-3 text-xs"><p className="m-0 text-[10px] text-slate-500">{key==="total_return"?"報酬":key==="cagr"?"CAGR":key==="max_drawdown"?"最大回撤":"Calmar"}</p><p className="mb-0 mt-1">中位數 {item?.median==null?"—":key==="calmar_ratio"?Number(item.median).toFixed(2):pct(item.median)}</p><p className="mb-0 mt-1 text-[10px] text-slate-500">範圍 {item?.min==null?"—":key==="calmar_ratio"?Number(item.min).toFixed(2):pct(item.min)} ～ {item?.max==null?"—":key==="calmar_ratio"?Number(item.max).toFixed(2):pct(item.max)}</p></div>})}</div></section>}
         {study.local_robustness?.radii&&<section className="panel p-4"><h2 className="m-0 text-sm">固定半徑摘要</h2><p className="mb-0 mt-1 text-[10px] text-slate-500">只彙總實際已執行且完整覆蓋的半徑；不足時不以部分週期冒充完整摘要。</p><div className="mt-3 grid gap-2 sm:grid-cols-4">{Object.entries(study.local_robustness.radii).map(([key,item])=>{const unavailable=item.status==="UNAVAILABLE_PERIODS_NOT_RUN";const labels:[[string,string],[string,string],[string,string],[string,string]]=[["報酬","total_return"],["CAGR","cagr"],["MDD","max_drawdown"],["Calmar","calmar_ratio"]];return <div key={key} className="rounded border border-[#27384d] bg-[#0a111b] p-3 text-xs"><p className="m-0 font-semibold">±{key}</p><p className={`mb-0 mt-1 text-[10px] ${unavailable?"text-amber-200":"text-emerald-200"}`}>{unavailable?"UNAVAILABLE — PERIODS NOT RUN":"COMPLETE"}</p><p className="mb-0 mt-1 text-[10px] text-slate-500">可用 {item.available_periods.join(", ")||"—"}</p><div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-[10px] text-slate-400">{labels.map(([label,metricKey])=>{const values=item.metrics[metricKey];const format=metricKey==="calmar_ratio"?(value:number|null)=>value==null?"—":Number(value).toFixed(2):(value:number|null)=>value==null?"—":pct(value);return <span key={metricKey}>{label} {format(values?.median??null)}<br/><span className="text-slate-600">{format(values?.min??null)} ～ {format(values?.max??null)}</span></span>})}</div></div>})}</div></section>}
         <section className="grid gap-3 sm:grid-cols-3"><MetricCard title="MA_LONG_BASELINE" run={baseline} accent="emerald"/><MetricCard title="MA_BOX_LONG_V1" run={active} accent="cyan"/><MetricCard title="BUY_AND_HOLD" run={bh} accent="violet"/></section>
        <section className="panel overflow-hidden"><header className="flex flex-wrap items-center justify-between gap-2 border-b border-[#223247] px-4 py-3"><div><h2 className="m-0 text-sm">SMA{period} 完整 K 線與箱型 audit</h2><p className="m-0 text-[10px] text-slate-500">邊界、突破、回踩、進出場與停損皆由 persisted event data 顯示</p></div>{active&&<div className="flex flex-wrap gap-2"><button onClick={()=>downloadJson(`${study.config.ticker}_SMA${period}_MA_BOX_LONG_V1.json`,active)} className="inline-flex min-h-9 items-center gap-2 rounded border border-cyan-400/25 px-3 py-2 text-xs text-cyan-200"><Download size={14}/>下載 audit JSON</button><button onClick={()=>downloadTradesCsv(`${study.config.ticker}_SMA${period}_trades.csv`,active.positions)} className="inline-flex min-h-9 items-center gap-2 rounded border border-cyan-400/25 px-3 py-2 text-xs text-cyan-200"><Download size={14}/>下載交易 CSV</button></div>}</header>{active?<EnhancedMaBoxChart run={active} focusTrade={focusTrade}/>:<p className="p-5 text-xs text-slate-500">此 period 尚無結果。</p>}</section>
        <section className="grid gap-3 lg:grid-cols-2"><TradeTable title="MA_BOX_LONG_V1 交易" rows={active?.positions??[]} onSelect={row=>setFocusTrade({entry:String(row.entry_date??""),exit:String(row.final_exit_date??"")})}/><EventTable rows={active?.events??[]}/></section>
        {active?.counterfactual_summary&&<section aria-label="Box filter counterfactual" className="panel p-4"><h2 className="m-0 text-sm">箱型過濾反事實比較</h2><div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">{Object.entries(active.counterfactual_summary).map(([key,value])=><div key={key} className="rounded border border-[#27384d] bg-[#0a111b] p-3"><p className="m-0 text-[10px] text-slate-500">{key}</p><p className="mb-0 mt-1 font-semibold">{typeof value === "number"&&key.includes("effect")?money(value):String(value??"—")}</p></div>)}</div></section>}
      </>}
    </div>
  </main>;
}

function Field({label,value,onChange,type="text"}:{label:string;value:string;onChange:(value:string)=>void;type?:string}) { return <label className="field"><span>{label}</span><input className="input" type={type} value={value} onChange={event=>onChange(event.target.value)}/></label>; }
function NumberField({label,value,onChange}:{label:string;value:number;onChange:(value:number)=>void}) { return <label className="field"><span>{label}</span><input className="input" type="number" min={0} value={value} onChange={event=>onChange(Number(event.target.value))}/></label>; }
function MetricCard({title,run,accent}:{title:string;run:MABoxRun|undefined;accent:"cyan"|"emerald"|"violet"}) { const color=accent==="cyan"?"text-cyan-200":accent==="emerald"?"text-emerald-200":"text-violet-200";return <article className="panel p-4"><h3 className={`m-0 text-xs ${color}`}>{title}</h3><div className="mt-3 grid grid-cols-2 gap-3 text-xs"><Pair label="期末資產" value={money(metric(run,"final_equity"))}/><Pair label="總報酬" value={pct(metric(run,"total_return"))}/><Pair label="年化報酬（CAGR）" value={pct(metric(run,"cagr"))}/><Pair label="最大回撤" value={pct(metric(run,"max_drawdown"))}/><Pair label="夏普值" value={metric(run,"sharpe_ratio")==null?"—":Number(metric(run,"sharpe_ratio")).toFixed(2)}/><Pair label="Calmar" value={metric(run,"calmar_ratio")==null?"—":Number(metric(run,"calmar_ratio")).toFixed(2)}/><Pair label="曝險比例" value={metric(run,"exposure_pct")==null?"—":`${Number(metric(run,"exposure_pct")).toFixed(1)}%`}/><Pair label="交易筆數" value={String(metric(run,"number_of_positions")??"—")}/></div></article>; }
function Pair({label,value}:{label:string;value:string}) { return <div><p className="m-0 text-[10px] text-slate-500">{label}</p><p className="m-0 mt-1 font-semibold">{value}</p></div>; }

function MaBoxChart({run}:{run:MABoxRun}) { const data=run.data.filter(row=>Number.isFinite(Number(row.close))&&Number.isFinite(Number(row.low))&&Number.isFinite(Number(row.high)));const W=1100,H=380,P=35;let lo=Infinity,hi=-Infinity;for(const row of data){lo=Math.min(lo,Number(row.low));hi=Math.max(hi,Number(row.high));}const span=Math.max(hi-lo,1);const x=(i:number)=>P+(data.length<=1?0:i/(data.length-1)*(W-P*2));const y=(v:number)=>H-P-(v-lo)/span*(H-P*2);const maPath=data.map((row,i)=>Number.isFinite(Number(row.ma))?`${i?"L":"M"}${x(i).toFixed(1)},${y(Number(row.ma)).toFixed(1)}`:"").filter(Boolean).join(" ");const byDate=new Map(data.map((row,i)=>[String(row.timestamp).slice(0,10),i]));const events=run.events.filter(event=>byDate.has(String(event.date??event.timestamp).slice(0,10)));return <div className="overflow-x-auto p-3"><svg role="img" aria-label="MA_BOX_LONG_V1 K 線與箱型圖" viewBox={`0 0 ${W} ${H}`} className="min-w-[760px] rounded border border-[#223247] bg-[#0a111b]"><rect x="0" y="0" width={W} height={H} fill="#0a111b"/>{data.map((row,i)=>{const open=Number(row.open),close=Number(row.close),high=Number(row.high),low=Number(row.low);const xx=x(i),bodyTop=y(Math.max(open,close)),bodyBottom=y(Math.min(open,close));return <g key={String(row.timestamp)}><line x1={xx} x2={xx} y1={y(high)} y2={y(low)} stroke="#64748b" strokeWidth="1"/><rect x={xx-1.5} y={bodyTop} width="3" height={Math.max(1,bodyBottom-bodyTop)} fill={close>=open?"#34d399":"#fb7185"}/></g>})}<path d={maPath} fill="none" stroke="#22d3ee" strokeWidth="1.5"/>{events.map((event,index)=>{const i=byDate.get(String(event.date??event.timestamp).slice(0,10))??0;const reason=String(event.reason_code??"");const isEntry=reason.includes("ENTRY");const isExit=reason.includes("EXIT");const color=isEntry?"#34d399":isExit?"#fb7185":reason.includes("BOX")?"#fbbf24":"#a78bfa";return <circle key={`${reason}-${index}`} cx={x(i)} cy={y(Number(event.close??data[i]?.close??0))} r="3" fill={color}><title>{`${String(event.date??"")} · ${reason} · SMA ${String(event.sma_period??run.sma_period)}`}</title></circle>})}<text x="12" y="18" fill="#94a3b8" fontSize="11">K 線 · SMA{run.sma_period} · {run.track}</text></svg><div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-400"><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-cyan-300"/>SMA</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-300"/>進場</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-rose-300"/>出場</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-300"/>箱型事件</span></div></div>; }

function EnhancedMaBoxChart({run,focusTrade}:{run:MABoxRun;focusTrade?:{entry?:string;exit?:string}|null}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const data = run.data.filter(row => Number.isFinite(Number(row.close)) && Number.isFinite(Number(row.low)) && Number.isFinite(Number(row.high)));
  const W = 1100, H = 430, P = 42;
  const chartWidth = W * zoom;
  const [panOffset, setPanOffset] = useState(0);
  if (!data.length) return <p className="p-5 text-xs text-slate-500">沒有可繪製的日線資料。</p>;
  let lo = Infinity, hi = -Infinity;
  data.forEach(row => { lo = Math.min(lo, Number(row.low)); hi = Math.max(hi, Number(row.high)); });
  const span = Math.max(hi - lo, 1);
  const y = (v:number) => H - P - (v - lo) / span * (H - P * 2);
  const byDate = new Map(data.map((row, i) => [String(row.timestamp).slice(0, 10), i]));
  const eventDate = (event:Record<string,unknown>) => String(event.date ?? event.timestamp ?? "").slice(0, 10);
  const events = run.events.filter(event => byDate.has(eventDate(event)));
  const focusStart = focusTrade?.entry ? byDate.get(focusTrade.entry.slice(0, 10)) : undefined;
  const focusEnd = focusTrade?.exit ? byDate.get(focusTrade.exit.slice(0, 10)) : undefined;
  // Clicking a trade focuses the entry-minus-20-bars through exit-plus-10-bars
  // window required by the frozen chart contract.  With no selected trade the
  // complete evaluation period remains visible.
  const focusedWindow = focusWindow(data.length, focusStart, focusEnd);
  const viewStart = focusedWindow.start;
  const viewEnd = focusedWindow.end;
  const viewSpan = Math.max(1, viewEnd - viewStart);
  const x = (i:number) => P + (i - viewStart) / viewSpan * (chartWidth - P * 2);
  let stopStarted = false;
  const stopPath = data.map((row, i) => {
    const value = Number(row.active_stop);
    if (!Number.isFinite(value)) { stopStarted = false; return ""; }
    const command = stopStarted ? "L" : "M"; stopStarted = true;
    return `${command}${x(i).toFixed(1)},${y(value).toFixed(1)}`;
  }).filter(Boolean).join(" ");
  // The backend emits an effective boundary for every session.  Draw these
  // session-start snapshots as a causal staircase: a value observed at the
  // close of t is first used at t+1.  Sparse update events are intentionally
  // not connected with a linear segment, because that would redraw history.
  const highStepPath = buildStepBoundaryPath(data, "box_high_effective", x, y);
  const lowStepPath = buildStepBoundaryPath(data, "box_low_effective", x, y);
  const positions = run.positions.map(position => ({
    start: byDate.get(String(position.entry_date ?? "").slice(0, 10)),
    end: byDate.get(String(position.final_exit_date ?? "").slice(0, 10)),
  })).filter(position => position.start !== undefined);
  const markerColor = (reason:string) => reason.includes("ENTRY") ? "#34d399" : reason.includes("EXIT") ? "#fb7185" : reason.includes("BOX") || reason.includes("RETEST") ? "#fbbf24" : "#a78bfa";
  const handleMouseMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0;
    setHoverIndex(Math.max(viewStart, Math.min(viewEnd, Math.round(viewStart + ratio * viewSpan))));
  };
  const handlePan = (event: React.UIEvent<HTMLDivElement>) => {
    const scrollLeft = event.currentTarget.scrollLeft;
    const windowWidth = Math.max(1, Math.min(data.length - 1, 100));
    const next = panViewport({from: panOffset, to: panOffset + windowWidth}, scrollLeft - panOffset, {min: 0, max: Math.max(data.length - 1, windowWidth)});
    setPanOffset(next.from);
  };
  return <div className="overflow-x-auto p-3" style={{touchAction:"pan-x pinch-zoom"}} onScroll={handlePan} data-pan-offset={panOffset} data-pan-range={`${panOffset}:${panOffset + Math.max(1, Math.min(data.length - 1, 100))}`}>
    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
      <span>圖表縮放</span>
      <button type="button" aria-label="放大圖表" onClick={()=>setZoom(zoomIn)} className="min-h-9 rounded border border-[#293a50] px-3 text-cyan-200">＋</button>
      <button type="button" aria-label="縮小圖表" onClick={()=>setZoom(zoomOut)} className="min-h-9 rounded border border-[#293a50] px-3 text-cyan-200">−</button>
      <button type="button" aria-label="重設完整範圍" onClick={()=>setZoom(resetZoom)} className="min-h-9 rounded border border-[#293a50] px-3">重設／完整範圍</button>
      <span>{Math.round(zoom * 100)}%</span>
    </div>
    <svg role="img" aria-label="MA_BOX_LONG_V1 K 線、SMA、箱型邊界與停損圖" viewBox={`0 0 ${chartWidth} ${H}`} width={chartWidth} height={H} className="min-w-[760px] rounded border border-[#223247] bg-[#0a111b]" onMouseMove={handleMouseMove} onMouseLeave={() => setHoverIndex(null)}>
      <rect x="0" y="0" width={chartWidth} height={H} fill="#0a111b"/>
      {focusStart !== undefined && <rect x={x(focusStart)} y={P} width={Math.max(3, x(focusEnd ?? focusStart) - x(focusStart))} height={H - P * 2} fill="#22d3ee" opacity=".12"/>}
      {positions.map((position, index) => <rect key={`hold-${index}`} x={x(position.start!)} y={P} width={Math.max(2, x(position.end ?? data.length - 1) - x(position.start!))} height={H - P * 2} fill="#34d399" opacity=".08"/>) }
      {data.map((row, i) => { const high = Number(row.box_high_effective), low = Number(row.box_low_effective); if (!Number.isFinite(high) || !Number.isFinite(low)) return null; const nextX = i < data.length - 1 ? x(i + 1) : x(i) + Math.max(2, (chartWidth - P * 2) / Math.max(1, viewSpan)); return <rect key={`shade-${String(row.timestamp)}`} x={x(i)} y={y(high)} width={Math.max(1, nextX - x(i))} height={Math.max(1, y(low) - y(high))} fill="#fbbf24" opacity=".07"/>; })}
      {highStepPath && <path d={highStepPath} fill="none" stroke="#fbbf24" strokeDasharray="5 4" data-boundary="box-high-step"/>}
      {lowStepPath && <path d={lowStepPath} fill="none" stroke="#fbbf24" strokeDasharray="5 4" data-boundary="box-low-step"/>}
      {/* sparse event paths intentionally removed; effective boundaries above are authoritative
        const highPath = "";
        const lowPath = "";
        return <g key={id}><rect x={x(first.i)} y={y(first.high)} width={Math.max(2, x(last.i) - x(first.i))} height={Math.max(1, y(first.low) - y(first.high))} fill="#fbbf24" opacity=".07"/><path d={highPath} fill="none" stroke="#fbbf24" strokeDasharray="5 4"/><path d={lowPath} fill="none" stroke="#fbbf24" strokeDasharray="5 4"/></g>;
      */}
      {data.map((row, i) => { const open = Number(row.open), close = Number(row.close), high = Number(row.high), low = Number(row.low), xx = x(i); return <g key={String(row.timestamp)}><line x1={xx} x2={xx} y1={y(high)} y2={y(low)} stroke="#64748b" strokeWidth="1"/><rect x={xx - 1.7} y={y(Math.max(open, close))} width="3.4" height={Math.max(1, y(Math.min(open, close)) - y(Math.max(open, close)))} fill={close >= open ? "#34d399" : "#fb7185"}/></g>; })}
      <path d={data.map((row, i) => Number.isFinite(Number(row.ma)) ? `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(row.ma)).toFixed(1)}` : "").filter(Boolean).join(" ")} fill="none" stroke="#22d3ee" strokeWidth="1.7"/>
      {stopPath && <path d={stopPath} fill="none" stroke="#fb7185" strokeWidth="1" strokeDasharray="3 3" opacity=".8"/>}
      {events.map((event, index) => { const i = byDate.get(eventDate(event)) ?? 0, reason = String(event.reason_code ?? ""); const position = event.position_id ? run.positions.find(item => String(item.position_id) === String(event.position_id)) : undefined; const tradeReturn = position?.return_pct == null ? "—" : pct(Number(position.return_pct) / 100); const holdingDays = position?.holding_days == null ? "—" : String(position.holding_days); const stop = event.stop == null ? "—" : money(event.stop); return <circle key={`${String(event.event_id ?? reason)}-${index}`} cx={x(i)} cy={y(Number(event.actual_fill ?? event.close ?? data[i]?.close ?? 0))} r="3.5" fill={markerColor(reason)}><title>{`${eventDate(event)} · ${reason} · 價格 ${money(event.actual_fill ?? event.close)} · SMA ${String(event.visual_ma ?? "—")} · 停損 ${stop} · 交易報酬 ${tradeReturn} · 持有 ${holdingDays} 日${event.BoxHigh == null ? "" : ` · 箱頂 ${money(event.BoxHigh)}`} ${event.BoxLow == null ? "" : `· 箱底 ${money(event.BoxLow)}`}`}</title></circle>; })}
      {hoverIndex !== null && <g pointerEvents="none"><line x1={x(hoverIndex)} x2={x(hoverIndex)} y1={P} y2={H - P} stroke="#94a3b8" strokeDasharray="2 3"/><text x={Math.min(chartWidth - 180, Math.max(8, x(hoverIndex) + 6))} y={H - 8} fill="#cbd5e1" fontSize="10">{String(data[hoverIndex]?.timestamp ?? "").slice(0, 10)} · {money(data[hoverIndex]?.close)}</text></g>}
      <text x="12" y="19" fill="#cbd5e1" fontSize="11">K 線 · SMA{run.sma_period} · {run.track}</text>
      <text x={chartWidth - 185} y="19" fill="#fb7185" fontSize="10">虛線：MA(t−1) −1.5% 停損</text>
    </svg>
    <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-400"><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-cyan-300"/>SMA</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-300"/>箱型邊界／事件</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-rose-300"/>停損／出場</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-300"/>持倉區間／進場</span><span>{focusStart === undefined ? "完整期間" : `已定位：前20根至後10根（${viewEnd - viewStart + 1} 根）`}</span><span>移動游標查看日期與收盤價</span></div>
  </div>;
}

function TradeTable({title,rows,onSelect}:{title:string;rows:Array<Record<string,unknown>>;onSelect?:(row:Record<string,unknown>)=>void}) { return <section className="panel overflow-hidden"><h2 className="border-b border-[#223247] px-4 py-3 text-sm">{title}</h2><div className="mobile-records p-3">{rows.map((row,i)=><button type="button" onClick={()=>onSelect?.(row)} key={i} className="block w-full rounded border border-[#27384d] bg-[#0a111b] p-3 text-left text-xs hover:border-cyan-300/50"><strong>{String(row.position_id??`position-${i+1}`)}</strong><p className="mb-0 mt-2 text-slate-400">{String(row.entry_date??"—")} → {String(row.final_exit_date??"—")}</p><p className="mb-0 mt-1">淨損益：{money(row.net_pnl)} · 報酬：{pct(Number(row.final_return))}</p><span className="mt-2 inline-block text-[10px] text-cyan-300">點擊定位圖表區間</span></button>)}{!rows.length&&<p className="text-xs text-slate-500">尚無完整交易。</p>}</div></section>; }
function EventTable({rows}:{rows:Array<Record<string,unknown>>}) { return <section className="panel overflow-hidden"><h2 className="border-b border-[#223247] px-4 py-3 text-sm">事件稽核</h2><div className="max-h-96 overflow-auto"><table className="table"><thead><tr><th>日期</th><th>事件代碼</th><th>狀態</th><th>箱頂</th><th>箱底</th></tr></thead><tbody>{rows.map((row,i)=><tr key={String(row.event_id??i)}><td>{String(row.date??row.timestamp??"—")}</td><td className="font-mono text-[10px] text-cyan-200">{String(row.reason_code??"—")}</td><td>{String(row.setup_state_before??"—")} → {String(row.setup_state_after??"—")}</td><td>{row.BoxHigh==null?"—":Number(row.BoxHigh).toFixed(2)}</td><td>{row.BoxLow==null?"—":Number(row.BoxLow).toFixed(2)}</td></tr>)}</tbody></table></div></section>; }
