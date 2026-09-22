"use client";

import { useState } from "react";
import type { XsmomSummary } from "@/lib/api";
import { num, t } from "@/lib/i18n";

export function XsmomStudy({ study }: { study: XsmomSummary }) {
  const [cash, setCash] = useState("CASH_ZERO");
  const metrics = study.cash_models[cash];
  const percent = (x: number | null) => x === null ? "—" : `${num(x * 100, 2)}%`;
  return <section id="cross-sectional-momentum" className="panel min-w-0 overflow-hidden" aria-label={t("Cross-sectional momentum benchmark study")}>
    <header className="border-b border-[#223247] p-4">
      <h2 className="m-0 text-sm">{t("Cross-sectional momentum benchmark study")}</h2>
      <p className="mb-0 mt-1 text-xs text-slate-400">{t("12-1 relative strength Top 3")} · {study.evaluation_start} → {study.evaluation_end}</p>
    </header>
    <div className="grid gap-3 p-3">
      <div className="flex flex-wrap items-center gap-3 text-xs"><strong className="text-amber-200">{t(study.grade)}</strong><span className="text-slate-400">{t("No candidate was created")}</span></div>
      <label className="grid gap-1 text-xs text-slate-400">{t("Cash model")}
        <select value={cash} onChange={e => setCash(e.target.value)} className="min-h-11 w-full rounded border border-[#293a50] bg-[#0a111b] px-3 text-slate-200 sm:max-w-sm">
          <option value="CASH_ZERO">{t("Zero-interest cash")}</option><option value="CASH_RISK_FREE">{t("Treasury-proxy cash yield")}</option>
        </select>
      </label>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Object.entries(metrics).map(([kind, m]) => <article key={kind} className="min-w-0 rounded border border-[#293a50] bg-[#0a111b] p-3">
        <h3 className="m-0 text-xs text-cyan-200">{t(({ RS: "12-1 relative strength Top 3", EW: "Eligible ETF equal-weight", SPY: "SPY Buy & Hold", QQQ: "QQQ Buy & Hold" } as Record<string, string>)[kind])}</h3>
        <dl className="mb-0 grid grid-cols-2 gap-2 text-xs">{[["Total Return", percent(m.total_return)], ["CAGR", percent(m.cagr)], ["Max Drawdown", percent(m.mdd)], ["Sharpe Ratio", m.sharpe === null ? "—" : num(m.sharpe, 2)], ["Exposure", percent(m.exposure)], ["Turnover", num(m.turnover, 2)]].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-[10px] text-slate-500">{t(label)}</dt><dd className="m-0 break-words">{value}</dd></div>)}</dl>
      </article>)}</div>
      <p className="m-0 text-xs leading-5 text-slate-400">{t("Monthly completed ranking, next-open execution; all comparisons share warm-up and costs.")}</p>
      <details className="technical-details min-w-0"><summary>{t("Technical details")}</summary><dl className="grid gap-2 text-[10px]">
        {[["Benchmark", study.study], ["Snapshot ID", study.registration.snapshot_id], ["Spec hash", study.registration.spec_sha256], ["Data fingerprint", study.registration.fingerprint]].map(([label, value]) => <div key={label}><dt className="text-slate-500">{t(label)}</dt><dd className="m-0 break-all">{value}</dd></div>)}
      </dl></details>
      <a href="/api/research/reports/cross-sectional-momentum-benchmark" target="_blank" rel="noreferrer" className="flex min-h-11 items-center justify-center rounded border border-cyan-400/30 px-4 text-xs font-semibold text-cyan-200">{t("Open report")}</a>
    </div>
  </section>;
}
