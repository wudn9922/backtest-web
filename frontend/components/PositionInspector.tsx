"use client";

import { t, messages, money as formatMoney, num, shares, dateText, warningText, errorText } from "@/lib/i18n";

import { useEffect } from "react";
import { AlertTriangle, ArrowRight, CalendarDays, LoaderCircle, X } from "lucide-react";
import { PositionAudit } from "@/lib/types";
import { PositionAuditChart } from "@/components/Charts";
import { resetAfterClose } from "@/lib/threshold-segments";


const money = (value: unknown) => value == null ? "—" : formatMoney(value);
const number = (value: unknown, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : num(value,digits);
const percent = (value: unknown, isDecimal = false) => value == null || !Number.isFinite(Number(value)) ? "—" : `${(Number(value) * (isDecimal ? 100 : 1)).toFixed(2)}%`;
const dateOnly = dateText;

type Props = { audit: PositionAudit | null; loading: boolean; error: string | null; onClose: () => void };

export function PositionInspector({ audit, loading, error, onClose }: Props) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", close); document.body.style.overflow = ""; };
  }, [onClose]);

  return <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={t("Position audit inspector")}>
    <section className="absolute inset-y-0 right-0 w-full overflow-y-auto border-l border-[#2a3b50] bg-[#09111b] shadow-2xl lg:w-[min(1180px,96vw)]">
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-[#223247] bg-[#0b1420]/95 px-4 py-3 backdrop-blur sm:px-6">
        <div><p className="m-0 text-[10px] font-semibold uppercase tracking-[.16em] text-cyan-300">{t("Trade audit")}</p><h2 className="mt-1 text-lg font-semibold">{audit ? `${audit.ticker} · ${audit.position_id}` : t("Position Inspector")}</h2></div>
        <button onClick={onClose} className="rounded-md border border-[#2a3b50] p-2 text-slate-400 hover:text-white" aria-label={t("Close position inspector")}><X size={18}/></button>
      </header>

      {loading && <div className="grid min-h-[60vh] place-items-center"><div className="flex items-center gap-3 text-sm text-cyan-200"><LoaderCircle className="animate-spin" size={20}/>{t("Loading position audit…")}</div></div>}
      {error && <div className="m-4 flex gap-3 rounded-lg border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-100"><AlertTriangle size={18}/><div><strong>{t("Audit unavailable")}</strong><p className="mb-0 mt-1 text-xs text-rose-100/75">{errorText(error)}</p><details className="mt-2"><summary>{t("Technical details")}</summary><pre className="technical-raw">{error}</pre></details></div></div>}
      {audit && <div className="grid gap-4 p-3 pb-10 sm:p-5 lg:p-6">
        <PositionSummary audit={audit}/>
        <section className="panel overflow-hidden"><header className="border-b border-[#223247] px-4 py-3"><h3 className="m-0 text-sm font-semibold">{t("Position price path")}</h3><p className="mb-0 mt-1 text-[10px] text-slate-500">{t("10 trading days before entry through 5 trading days after exit · touch pan and pinch zoom enabled")}</p></header><div className="p-2 sm:p-3"><PositionAuditChart audit={audit}/></div></section>
        <section><div className="mb-3 flex items-end justify-between gap-3"><div><h3 className="m-0 text-sm font-semibold">{t("Daily strategy timeline")}</h3><p className="mb-0 mt-1 text-[10px] text-slate-500">{t("Backend-recorded states, thresholds, validations and events for every holding day")}</p></div><span className="rounded border border-[#293a50] px-2 py-1 text-[10px] text-slate-400">{messages.tradingDays(audit.timeline.length)}</span></div><div className="grid gap-2">{audit.timeline.map((item, index) => <AuditDayCard key={item.timestamp} item={item} presentation={audit.presentation} initiallyOpen={index === 0 || item.ambiguity.applied}/>)}</div></section>
      </div>}
    </section>
  </div>;
}

function PositionSummary({ audit }: { audit: PositionAudit }) {
  const p = audit.position;
  const slippageCost = audit.chart.executions.reduce((total, execution) => total + execution.slippage, 0);
  const stopPercent = audit.presentation?.ma_stop.percent_below_ma ?? 1.5;
  const exitReason = p.exit_final_close_reason === "MA_EXIT" ? messages.simpleMaStopExit(stopPercent) : t(p.exit_final_close_reason ?? "—");
  const items = [
    ["Ticker", audit.ticker], ["Strategy", audit.strategy], ["Entry date", dateOnly(p.entry_date)], ["Entry price", money(p.entry_price)],
    ["Q0", shares(p.q0 ?? p.initial_shares)], ["Final exit", dateOnly(p.final_exit_date)], ["Final return", percent(p.final_return, true)], ["Realized PnL", money(p.realized_pnl ?? p.net_pnl)],
    ["Gross PnL", money(p.gross_pnl)], ["Commission", money(p.fees)], ["Slippage cost (included)", money(slippageCost)], ["Holding days", number(p.holding_days, 0)], ["Exit reason", exitReason],
  ];
  return <section className="panel p-3 sm:p-4"><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md bg-[#223247] sm:grid-cols-3 xl:grid-cols-6">{items.map(([label, value]) => <div key={String(label)} className="min-w-0 bg-[#101925] p-3"><p className="m-0 text-[9px] font-semibold uppercase tracking-wide text-slate-500">{t(label)}</p><p className="mb-0 mt-1 break-words text-sm font-semibold text-slate-100">{t(value)}</p></div>)}</div><p className="mb-0 mt-3 text-[10px] text-slate-400">{t("Gross PnL uses execution prices and excludes commissions. Realized PnL subtracts all commissions. Slippage is already included in execution prices and is not deducted again.")}</p></section>;
}

function AuditDayCard({ item, presentation, initiallyOpen }: { item: PositionAudit["timeline"][number]; presentation: PositionAudit["presentation"]; initiallyOpen: boolean }) {
  const breakReset = resetAfterClose(item.events);
  const stopPercent = presentation?.ma_stop.percent_below_ma ?? 1.5;
  const stopMultiplier = presentation?.ma_stop.multiplier ?? 0.985;
  const activeStop = item.thresholds.simple_ma_exit_stop ?? item.thresholds.ma_half_stop;
  const entryZone = item.entry_zone ?? { lower_entry: null, upper_entry: null, entry_allowed: null, entry_missed: null, entry_execution_price: null, intrabar_assumption: "Legacy" };
  const thresholds: Array<[string, unknown]> = [
    ["Breakout trigger", item.thresholds.breakout_trigger], ["Entry level", item.thresholds.entry_level], ["Day1 Stop", item.thresholds.day1_stop],
    [messages.simpleMaStopLine(stopPercent), item.thresholds.simple_ma_exit_stop], [messages.maHalfStopLine(stopPercent), item.thresholds.ma_half_stop], [breakReset ? "BreakDayLow (intraday only)" : "BreakDayLow", item.thresholds.break_day_low],
    ["First TP", item.thresholds.first_tp_price], ["Protective stop", item.thresholds.protective_stop], ["Bias extreme", item.thresholds.bias_extreme_threshold_price], ["ATR extreme", item.thresholds.atr_extreme_threshold_price],
  ];
  return <details className={`group overflow-hidden rounded-lg border bg-[#0d1622] ${item.ambiguity.applied ? "border-amber-400/50" : "border-[#223247]"}`} open={initiallyOpen}>
    <summary className="cursor-pointer list-none px-3 py-3 sm:px-4"><div className="grid items-center gap-2 sm:grid-cols-[120px_1fr_auto]">
      <div className="flex items-center gap-2"><CalendarDays size={14} className="text-cyan-300"/><strong className="text-xs">{item.date}</strong></div>
      <div className="flex min-w-0 items-center gap-2 text-[10px] text-slate-400"><span className="truncate">{t(item.strategy_state_at_open)}</span><ArrowRight size={11}/><span className="truncate">{t(item.strategy_state_at_close)}</span></div>
      <div className="flex gap-3 text-[10px] text-slate-400"><span>{messages.quantityChange(item.current_quantity_at_open,item.current_quantity_at_close)}</span><span>{messages.events(item.events.length)}</span></div>
    </div><div className="mt-2 grid grid-cols-5 gap-1 text-[10px] text-slate-400">{[["O",item.open],["H",item.high],["L",item.low],["C",item.close],["Vol",item.volume]].map(([label,value])=><span key={String(label)}><b className="text-slate-600">{t(label)}</b> {number(value)}</span>)}</div></summary>
    <div className="grid gap-3 border-t border-[#223247] p-3 sm:p-4">
      {breakReset && <p className="m-0 rounded-md border border-cyan-400/25 bg-cyan-400/5 p-3 text-xs text-cyan-100">{t("BreakDayLow active intraday · Reset after close. This episode’s threshold is inactive after this close; a later half-stop may establish a new episode.")}</p>}
      {item.ambiguity.applied && <div className="rounded-md border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100"><div className="flex gap-2 font-semibold"><AlertTriangle size={15}/>{warningText(item.ambiguity.message)}</div><p className="mb-0 mt-1 text-[10px] text-amber-100/70">{t("Simultaneous conditions:")}{item.ambiguity.simultaneous_conditions.map(t).join(" + ") || t("Recorded in event metadata")}</p></div>}
      <div className="grid gap-3 lg:grid-cols-3">
        <AuditGrid title={t("Daily market data")} items={[["Open",item.open],["High",item.high],["Low",item.low],["Close",item.close],["Volume",item.volume],["Qty open / close",`${item.current_quantity_at_open} / ${item.current_quantity_at_close}`]]}/>
        <p className="m-0 text-[10px] text-slate-400">{t("ma.help")}</p><AuditGrid title={t("Completed indicators")} items={[["Previous-day MA",item.previous_day_ma],["Current-day MA",item.current_day_ma],["Previous-day ATR",item.previous_day_atr],["Bias sigma",item.bias_sigma],["State at open",item.strategy_state_at_open],["State at close",item.strategy_state_at_close]]}/>
        <AuditGrid title={t("Strategy thresholds")} items={thresholds}/>
      </div>
      {activeStop != null && <div className="rounded-md border border-orange-400/25 bg-orange-400/5 p-3 text-xs text-orange-100"><strong className="block break-words">{item.thresholds.simple_ma_exit_stop != null ? messages.simpleMaStopLine(stopPercent) : messages.maHalfStopLine(stopPercent)}</strong><p className="mb-0 mt-1 text-[11px] leading-5 text-orange-100/80">{messages.maStopHelp(stopPercent, stopMultiplier)}</p><p className="mb-0 mt-1 break-all font-mono text-[10px] text-orange-200/60">{presentation?.ma_stop.formula ?? `MA(t-1) × ${stopMultiplier}`}</p></div>}
      <AuditGrid title={t("Entry Zone v2")} items={[["LowerEntry",entryZone.lower_entry],["UpperEntry",entryZone.upper_entry],["Entry allowed?",entryZone.entry_allowed == null ? "—" : entryZone.entry_allowed ? "YES" : "NO"],["Entry missed?",entryZone.entry_missed == null ? "—" : entryZone.entry_missed ? "YES" : "NO"],["Entry execution",entryZone.entry_execution_price],["Intrabar assumption",entryZone.intrabar_assumption]]}/>
      {(item.validations.entry_day_volume || item.validations.day2_confirmation) && <div className="grid gap-2 sm:grid-cols-2">{item.validations.entry_day_volume && <Validation title={t("Entry Day Volume")} data={item.validations.entry_day_volume}/>} {item.validations.day2_confirmation && <Validation title={t("Day 2 Confirmation")} data={item.validations.day2_confirmation}/>}</div>}
      <div><h4 className="mb-2 text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500">{t("Daily events")}</h4>{item.events.length ? <div className="grid gap-2">{item.events.map((event, index) => <div key={`${t(event.event)}-${index}`} className="min-w-0 rounded-md border border-[#223247] bg-[#09111b] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="break-words text-xs text-cyan-200">{eventDisplayName(event.source_event || event.event, stopPercent)}</strong><details className="technical-details"><summary>{t("Technical details")}</summary><pre className="technical-raw">{JSON.stringify(event,null,2)}</pre></details><span className="break-words text-[10px] text-slate-500">{t(event.state_before)} → {t(event.state_after)}</span></div><div className="mt-2 grid grid-cols-2 gap-2 text-[10px] sm:grid-cols-5"><Pair label={t("Trigger")} value={money(event.trigger_level)}/><Pair label={t("Execution")} value={money(event.execution_price)}/><Pair label={t("Shares before")} value={number(event.shares_before,0)}/><Pair label={t("Shares sold")} value={number(event.shares_sold,0)}/><Pair label={t("Remaining")} value={number(event.shares_remaining,0)}/></div>{event.stop_execution && <StopExecutionDetails detail={event.stop_execution}/>}</div>)}</div> : <p className="m-0 rounded-md border border-dashed border-[#293a50] p-3 text-xs text-slate-600">{t("No strategy event on this trading day.")}</p>}</div>
    </div>
  </details>;
}

function eventDisplayName(code: string, stopPercent: number): string {
  if (code === "MA_EXIT") return messages.simpleMaStopExit(stopPercent);
  if (["MA_BREAK_HALF_EXIT", "MA_HALF_EXIT", "BREAK_HALF_TRIGGERED"].includes(code)) return messages.maHalfStopLine(stopPercent);
  return t(code);
}

function StopExecutionDetails({ detail }: { detail: NonNullable<PositionAudit["timeline"][number]["events"][number]["stop_execution"]> }) {
  const gap = detail.trigger_type === "GAP_THROUGH";
  const explanation = gap ? "The open was already at or below the stop, so the open is the raw fill basis." : "The open remained above the stop. The intraday low crossed it, so the raw fill is the stop price.";
  return <section className="mt-3 min-w-0 rounded-md border border-orange-400/30 bg-orange-400/5 p-3" aria-label={t("Stop execution details")}>
    <div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-xs text-orange-200">{t("Stop execution details")}</strong><span className="rounded bg-orange-400/10 px-2 py-1 text-[10px] font-semibold text-orange-100">{t(gap ? "Gap-through stop" : "Intraday stop")}</span></div>
    <p className="mb-0 mt-2 break-words text-[11px] leading-5 text-orange-100/80">{t(explanation)}</p>
    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Pair label={t("Previous-day MA")} value={money(detail.reference_ma)}/><Pair label={t("Active stop")} value={money(detail.active_stop_price)}/>
      <Pair label={t("Open")} value={money(detail.open_price)}/><Pair label={t("Low")} value={money(detail.low_price)}/>
      <Pair label={t("Trigger method")} value={t(gap ? "Gap-through stop" : "Intraday stop")}/><Pair label={t("Raw fill")} value={money(detail.raw_fill_price)}/>
      <Pair label={t("Actual execution")} value={money(detail.actual_execution_price)}/><Pair label={t("Sell slippage")} value={percent(detail.sell_slippage_pct)}/>
    </div>
    <p className="mb-0 mt-2 break-all font-mono text-[10px] text-orange-200/55">{t("Formula")}：{detail.formula}</p>
  </section>;
}

function AuditGrid({ title, items }: { title: string; items: Array<[string, unknown]> }) { return <section className="rounded-md border border-[#223247] bg-[#09111b] p-3"><h4 className="m-0 text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500">{t(title)}</h4><div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2">{items.map(([label,value])=><Pair key={t(label)} label={t(label)} value={typeof value === "number" ? number(value, 4) : String(value ?? "—")}/>)}</div></section>; }
function Pair({ label, value }: { label: string; value: string }) { return <div className="min-w-0"><p className="m-0 truncate text-[9px] uppercase tracking-wide text-slate-600">{t(label)}</p><p className="m-0 break-words text-[11px] font-medium text-slate-200">{t(value)}</p></div>; }
function Validation({ title, data }: { title: string; data: Record<string, number | string | null> }) { const status=String(data.status); return <section className="rounded-md border border-[#293a50] bg-[#0a121d] p-3"><div className="flex items-center justify-between"><h4 className="m-0 text-xs font-semibold">{t(title)}</h4><span className={`rounded px-2 py-0.5 text-[9px] font-bold ${status === "PASS" ? "bg-emerald-400/15 text-emerald-300" : "bg-rose-400/15 text-rose-300"}`}>{t(status)}</span></div><div className="mt-2 grid grid-cols-2 gap-2">{Object.entries(data).filter(([key])=>key!=="status").map(([key,value])=><Pair key={key} label={t(key)} value={key.includes("pct") ? percent(value) : number(value,4)}/>)}</div></section>; }
