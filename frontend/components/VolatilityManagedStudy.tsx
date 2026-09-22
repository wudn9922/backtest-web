"use client";

import { useState } from "react";
import type { VolatilityManagedSummary } from "@/lib/api";
import { num, t } from "@/lib/i18n";

export function VolatilityManagedStudy({study}:{study:VolatilityManagedSummary}) {
  const [cash,setCash]=useState("CASH_ZERO");
  const pair=study.primary_spy[cash];
  const breadth=study.robustness_summary[cash];
  const pct=(value:number|null|undefined)=>value==null?"—":`${num(value*100,2)}%`;
  const metric=(title:string,value:string,detail:string)=><article className="min-w-0 rounded-lg border border-[#293a50] bg-[#0a111b] p-3"><p className="m-0 text-[10px] text-slate-500">{t(title)}</p><strong className="mt-1 block break-words text-base text-slate-100">{value}</strong><p className="mb-0 mt-1 break-words text-[10px] leading-4 text-slate-500">{detail}</p></article>;
  const crises=study.crisis_analysis[cash];
  const stress=study.cost_stress_spy[cash]["2X_BOTH"];
  return <section id="volatility-managed-exposure" className="panel min-w-0 overflow-hidden" aria-label={t("Volatility-managed exposure benchmark study")}>
    <header className="border-b border-[#223247] p-4"><h2 className="m-0 text-sm">{t("Volatility-managed exposure benchmark study")}</h2><p className="mb-0 mt-1 text-xs text-slate-400">{t("20-day volatility-managed exposure")} · {study.evaluation.evaluation_start} → {study.evaluation.evaluation_end}</p></header>
    <div className="grid gap-3 p-3">
      <div className="flex flex-wrap items-center gap-3"><strong className="text-sm text-amber-200">{t(study.evidence_grade)}</strong><span className="text-xs text-slate-400">NEXT FAMILY = {study.next_family}</span></div>
      <div className="grid gap-2 rounded-lg border border-violet-400/20 bg-violet-400/5 p-3 text-xs text-violet-100 sm:grid-cols-4"><span>{t("20-day realized volatility")}</span><span>{t("15% target volatility")}</span><span>{t("Maximum 100% equity exposure")}</span><span>{t("Remaining allocation held as cash")}</span></div>
      <label className="grid gap-1 text-xs text-slate-400">{t("Cash model")}<select value={cash} onChange={event=>setCash(event.target.value)} className="min-h-11 w-full rounded border border-[#293a50] bg-[#0a111b] px-3 text-slate-200 sm:max-w-sm"><option value="CASH_ZERO">{t("Zero-interest cash")}</option><option value="CASH_RISK_FREE">{t("Treasury-proxy cash yield")}</option></select></label>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metric("SPY Sharpe delta",pair.delta.sharpe==null?"—":num(pair.delta.sharpe,2),`${num(pair.managed.sharpe??0,2)} vs ${num(pair.buy_hold.sharpe??0,2)}`)}
        {metric("SPY maximum drawdown delta",pct(pair.delta.mdd),`${pct(pair.managed.mdd)} vs ${pct(pair.buy_hold.mdd)}`)}
        {metric("SPY CAGR delta",pct(pair.delta.cagr),`${pct(pair.managed.cagr)} vs ${pct(pair.buy_hold.cagr)}`)}
        {metric("SPY average exposure",pct(pair.managed.exposure),`${t("Average cash")} ${pct(pair.managed.cash_pct)}`)}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metric("ETF Sharpe improvement",`${breadth.improvement_counts.sharpe} / ${breadth.etfs}`,`${t("Median delta")} ${num(breadth.median_delta.sharpe,2)}`)}
        {metric("ETF MDD improvement",`${breadth.improvement_counts.mdd} / ${breadth.etfs}`,`${t("Median delta")} ${pct(breadth.median_delta.mdd)}`)}
        {metric("ETF Calmar improvement",`${breadth.improvement_counts.calmar} / ${breadth.etfs}`,`${t("Median delta")} ${num(breadth.median_delta.calmar,2)}`)}
        {metric("Cash-yield contribution",`${num(study.cash_decomposition.SPY.managed_return_contribution_pp,2)} pp`,`${t("Incremental effect")} ${num(study.cash_decomposition.SPY.incremental_managed_cash_effect_pp,2)} pp`)}
      </div>
      <div className="grid gap-3 md:grid-cols-3"><div className="rounded border border-[#293a50] p-3 text-xs"><strong>{t("Crisis behavior")}</strong><p className="mb-0 mt-2 leading-5 text-slate-400">{crises.filter(row=>row.delta.mdd>0).length}/{crises.length} {t("episodes reduced maximum drawdown")} · {t("Lowest target exposure")} {pct(Math.min(...crises.map(row=>row.minimum_target_exposure)))}</p></div><div className="rounded border border-[#293a50] p-3 text-xs"><strong>{t("Cost attribution")}</strong><p className="mb-0 mt-2 leading-5 text-slate-400">2× {t("Commission and slippage")} · Sharpe Δ {num((stress.delta?.sharpe)??((stress.managed.sharpe??0)-(stress.buy_hold.sharpe??0)),2)}</p></div><div className="rounded border border-[#293a50] p-3 text-xs"><strong>{t("Walk-forward")}</strong><p className="mb-0 mt-2 leading-5 text-slate-400">Sharpe {study.walk_forward_summary.spy_unique_tests.sharpe}/{study.walk_forward_summary.spy_unique_tests.cells} · MDD {study.walk_forward_summary.spy_unique_tests.mdd}/{study.walk_forward_summary.spy_unique_tests.cells}</p></div></div>
      <details className="technical-details min-w-0"><summary>{t("Technical details")}</summary><dl className="grid gap-2 text-[10px]">{[["Benchmark",study.study],["Snapshot ID",study.registration.snapshot_id],["Spec hash",study.registration.spec_sha256],["Data fingerprint",study.registration.fingerprint]].map(([label,value])=><div key={label}><dt className="text-slate-500">{t(label)}</dt><dd className="m-0 break-all">{value}</dd></div>)}</dl></details>
      <a href="/api/research/reports/volatility-managed-benchmark" target="_blank" rel="noreferrer" className="flex min-h-11 items-center justify-center rounded border border-cyan-400/30 px-4 text-xs font-semibold text-cyan-200">{t("Open report")}</a>
    </div>
  </section>;
}
