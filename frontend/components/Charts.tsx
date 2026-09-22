"use client";

import { t, messages, money as formatMoney, shares } from "@/lib/i18n";

import { useEffect, useRef } from "react";
import { createChart, ColorType, IChartApi, LineStyle, Time } from "lightweight-charts";
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BacktestResult, PositionAudit } from "@/lib/types";
import { HISTORICAL_THRESHOLD_OPTIONS, resetAfterClose, thresholdSegments } from "@/lib/threshold-segments";

const day = (value: string) => value.slice(0, 10) as Time;

export function StockChart({ result, focusTimestamp }: { result: BacktestResult; focusTimestamp?: string }) {
  const container = useRef<HTMLDivElement>(null); const chartRef = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!container.current) return;
    const chartHeight = container.current.clientWidth < 600 ? 340 : 430;
    const chart = createChart(container.current, { height: chartHeight, layout: { background: { type: ColorType.Solid, color: "#0e1622" }, textColor: "#8091a7" }, grid: { vertLines: { color: "#172333" }, horzLines: { color: "#172333" } }, rightPriceScale: { borderColor: "#26384e" }, localization: { locale: "zh-TW", dateFormat: "yyyy-MM-dd" }, timeScale: { borderColor: "#26384e", timeVisible: false }, handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }, handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true } });
    chartRef.current = chart;
    const candles = chart.addCandlestickSeries({ upColor: "#34d399", downColor: "#fb7185", borderVisible: false, wickUpColor: "#34d399", wickDownColor: "#fb7185" });
    candles.setData(result.daily_data.map(row => ({ time: day(String(row.timestamp)), open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close) })));
    const ma = chart.addLineSeries({ color: "#22d3ee", lineWidth: 2, title: t("Reference MA") });
    ma.setData(result.daily_data.filter(row => row.reference_ma != null).map(row => ({ time: day(String(row.timestamp)), value: Number(row.reference_ma) })));
    const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "volume", color: "#334155" });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: .82, bottom: 0 } });
    volume.setData(result.daily_data.map(row => ({ time: day(String(row.timestamp)), value: Number(row.volume), color: Number(row.close) >= Number(row.open) ? "#1f6f5a88" : "#7f334588" })));
    candles.setMarkers(result.executions.map(execution => ({ time: day(execution.timestamp), position: execution.side === "BUY" ? "belowBar" as const : "aboveBar" as const, color: execution.side === "BUY" ? "#22d3ee" : execution.event_type.includes("TP") ? "#fbbf24" : "#fb7185", shape: execution.side === "BUY" ? "arrowUp" as const : "arrowDown" as const, text: `${t(execution.event_type)} ${shares(execution.quantity)}@${formatMoney(execution.price)}` })));
    chart.timeScale().fitContent();
    const resize = new ResizeObserver(entries => chart.applyOptions({ width: entries[0].contentRect.width, height: entries[0].contentRect.width < 600 ? 340 : 430 })); resize.observe(container.current);
    return () => { resize.disconnect(); chart.remove(); chartRef.current = null; };
  }, [result]);
  useEffect(() => {
    if (!chartRef.current || !focusTimestamp) return;
    const target = new Date(focusTimestamp); const from = new Date(target); const to = new Date(target); from.setDate(from.getDate() - 15); to.setDate(to.getDate() + 15);
    chartRef.current.timeScale().setVisibleRange({ from: from.toISOString().slice(0, 10) as Time, to: to.toISOString().slice(0, 10) as Time });
  }, [focusTimestamp]);
  return <div ref={container} className="w-full touch-pan-y overflow-hidden" aria-label={t("Candlestick, volume, reference MA and trade marker chart")}/>;
}

export function PositionAuditChart({ audit }: { audit: PositionAudit }) {
  const container = useRef<HTMLDivElement>(null);
  const stopPercent = audit.presentation?.ma_stop.percent_below_ma ?? 1.5;
  const hasSimpleStop = audit.chart.daily_data.some(row => row.simple_ma_exit_stop != null);
  const hasHalfStop = audit.chart.daily_data.some(row => row.ma_half_stop != null);
  useEffect(() => {
    if (!container.current) return;
    const height = container.current.clientWidth < 600 ? 320 : 390;
    const chart = createChart(container.current, { height, layout: { background: { type: ColorType.Solid, color: "#0b131e" }, textColor: "#8091a7" }, grid: { vertLines: { color: "#172333" }, horzLines: { color: "#172333" } }, rightPriceScale: { borderColor: "#26384e" }, localization: { locale: "zh-TW", dateFormat: "yyyy-MM-dd" }, timeScale: { borderColor: "#26384e" }, handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }, handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true } });
    const rows = audit.chart.daily_data;
    const candles = chart.addCandlestickSeries({ upColor: "#34d399", downColor: "#fb7185", borderVisible: false, wickUpColor: "#34d399", wickDownColor: "#fb7185" });
    candles.setData(rows.map(row => ({ time: day(String(row.timestamp)), open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close) })));
    const addThreshold = (key: string, title: string, color: string, width: 1 | 2 = 1) => {
      const boundaries = key === "break_day_low"
        ? new Set(audit.timeline.filter(item => resetAfterClose(item.events)).map(item => item.date))
        : new Set<string>();
      for (const segment of thresholdSegments(rows, key, boundaries)) {
        const series = chart.addLineSeries({ ...HISTORICAL_THRESHOLD_OPTIONS, color, lineWidth: width, lineStyle: LineStyle.Dashed, title: t(title) });
        series.setData(segment);
      }
    };
    const ma = chart.addLineSeries({ color: "#22d3ee", lineWidth: 2, title: t("Reference MA") });
    ma.setData(rows.filter(row => row.reference_ma != null).map(row => ({ time: day(String(row.timestamp)), value: Number(row.reference_ma) })));
    addThreshold("simple_ma_exit_stop", messages.simpleMaStopLine(stopPercent), "#f97316", 2);
    addThreshold("ma_half_stop", messages.maHalfStopLine(stopPercent), "#fb923c", 2);
    addThreshold("break_day_low", "Break low", "#fb7185");
    addThreshold("day1_stop", "Day1 Stop", "#ef4444", 2);
    addThreshold("first_tp_price", "First TP", "#fbbf24");
    addThreshold("protective_stop", "Protective", "#f472b6", 2);
    candles.setMarkers(audit.chart.executions.map(execution => {
      const code = execution.reason || execution.event_type;
      const label = code === "MA_EXIT"
        ? messages.simpleMaStopExit(stopPercent)
        : ["MA_BREAK_HALF_EXIT", "MA_HALF_EXIT", "BREAK_HALF_TRIGGERED"].includes(code)
          ? messages.maHalfStopLine(stopPercent)
          : t(execution.event_type);
      return { time: day(execution.timestamp), position: execution.side === "BUY" ? "belowBar" as const : "aboveBar" as const, color: execution.side === "BUY" ? "#22d3ee" : execution.event_type.includes("TP") ? "#fbbf24" : "#fb7185", shape: execution.side === "BUY" ? "arrowUp" as const : "arrowDown" as const, text: `${label} ${shares(execution.quantity)}@${formatMoney(execution.price)}` };
    }));
    chart.timeScale().fitContent();
    const resize = new ResizeObserver(entries => chart.applyOptions({ width: entries[0].contentRect.width, height: entries[0].contentRect.width < 600 ? 320 : 390 }));
    resize.observe(container.current);
    return () => { resize.disconnect(); chart.remove(); };
  }, [audit]);
  return <div className="min-w-0">
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-2 px-1 text-[10px] text-slate-300" aria-label={t("Chart legend")}>
      <span className="flex min-w-0 items-center gap-1.5"><i className="h-0.5 w-5 shrink-0 bg-cyan-400"/>{t("Reference MA")}</span>
      {hasSimpleStop && <span className="flex min-w-0 items-center gap-1.5 break-words"><i className="h-0.5 w-5 shrink-0 bg-orange-500"/>{messages.simpleMaStopLine(stopPercent)}</span>}
      {hasHalfStop && <span className="flex min-w-0 items-center gap-1.5 break-words"><i className="h-0.5 w-5 shrink-0 bg-orange-400"/>{messages.maHalfStopLine(stopPercent)}</span>}
    </div>
    <div ref={container} className="w-full touch-pan-y overflow-hidden" aria-label={t("Position candlestick audit chart with MA and strategy thresholds")}/>
  </div>;
}

export function EquityChart({ result }: { result: BacktestResult }) {
  const data = result.equity_curve.map(row => ({ ...row, date: row.timestamp.slice(0, 10) }));
  return <div className="h-[280px]"><ResponsiveContainer><LineChart data={data} margin={{left: 8, right: 20, top: 16, bottom: 4}}><CartesianGrid stroke="#172333" vertical={false}/><XAxis dataKey="date" stroke="#718198" tick={{fontSize: 10}} minTickGap={45}/><YAxis stroke="#718198" tick={{fontSize: 10}} tickFormatter={v => `$${Math.round(v/1000)}k`}/><Tooltip formatter={(v:number)=>formatMoney(v)} contentStyle={{background:"#0a111b",border:"1px solid #293a50",fontSize:12}}/><Legend/><Line type="monotone" dataKey="strategy" name={t("Strategy")} stroke="#22d3ee" strokeWidth={2} dot={false}/><Line type="monotone" dataKey="buy_hold" name={t("Buy & hold")} stroke="#94a3b8" strokeWidth={1.5} dot={false}/></LineChart></ResponsiveContainer></div>;
}

export function DrawdownChart({ result }: { result: BacktestResult }) {
  const data = result.drawdown.map(row => ({ date: row.timestamp.slice(0, 10), drawdown: row.drawdown * 100 }));
  return <div className="h-[220px]"><ResponsiveContainer><AreaChart data={data} margin={{left: 8, right: 20, top: 12, bottom: 4}}><defs><linearGradient id="dd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fb7185" stopOpacity=".55"/><stop offset="1" stopColor="#fb7185" stopOpacity=".05"/></linearGradient></defs><CartesianGrid stroke="#172333" vertical={false}/><XAxis dataKey="date" stroke="#718198" tick={{fontSize:10}} minTickGap={45}/><YAxis stroke="#718198" tick={{fontSize:10}} tickFormatter={v => `${v}%`}/><Tooltip contentStyle={{background:"#0a111b",border:"1px solid #293a50",fontSize:12}} formatter={(v: number) => `${v.toFixed(2)}%`}/><Area type="monotone" dataKey="drawdown" name={t("Drawdown")} stroke="#fb7185" fill="url(#dd)"/></AreaChart></ResponsiveContainer></div>;
}

export function MonthlyHeatmap({ result }: { result: BacktestResult }) {
  const years = [...new Set(result.monthly_returns.map(item => item.year))]; const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const cell=(year:number,index:number)=>{ const value=result.monthly_returns.find(item=>item.year===year&&item.month===index+1)?.return; const alpha=value==null?0:Math.min(.8,.15+Math.abs(value)*8); return {value,label:value==null?"—":`${(value*100).toFixed(1)}%`,background:value==null?"#111b28":value>=0?`rgba(52,211,153,${alpha})`:`rgba(251,113,133,${alpha})`}; };
  return <><div className="mobile-month-table overflow-x-auto"><table className="w-full border-separate border-spacing-1 text-center text-[11px]"><thead><tr><th/><>{months.map(m => <th className="px-2 py-1 text-slate-500" key={m}>{t(m)}</th>)}</></tr></thead><tbody>{years.map(year => <tr key={year}><th className="pr-2 text-slate-400">{year}</th>{months.map((_, index) => { const item=cell(year,index); return <td key={index} className="rounded px-2 py-2" style={{background:item.background}}>{item.label}</td>})}</tr>)}</tbody></table></div><div className="mobile-month-grid">{years.flatMap(year=>months.map((month,index)=>{const item=cell(year,index);return <div key={`${year}-${month}`} className="rounded p-2 text-center" style={{background:item.background}}><p className="m-0 text-[9px] text-slate-400">{year} {t(month)}</p><p className="m-0 text-[11px] font-semibold">{item.label}</p></div>}))}</div></>;
}
