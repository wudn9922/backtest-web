"use client";

import { t, messages, money as formatMoney } from "@/lib/i18n";

import { FormState } from "@/lib/types";
import { ChevronDown, Play, RotateCcw } from "lucide-react";

type Props = { form: FormState; setForm: (value: FormState) => void; running: boolean; progressStage: string; onRun: () => void };
type FieldProps = { label: string; children: React.ReactNode; wide?: boolean };

const Field = ({ label, children, wide }: FieldProps) => <div className={`field ${wide ? "settings-wide" : ""}`}><label>{t(label)}</label>{children}</div>;

function Section({ title, hint, open = false, children }: { title: string; hint?: string; open?: boolean; children: React.ReactNode }) {
  return <details className="settings-section" open={open}>
    <summary><span><strong>{t(title)}</strong>{hint && <small>{t(hint)}</small>}</span><ChevronDown size={15}/></summary>
    <div className="settings-grid">{children}</div>
  </details>;
}

export function SettingsPanel({ form, setForm, running, progressStage, onRun }: Props) {
  const isAdvanced = form.strategy !== "simple";
  const strategyLabels = { simple: "Simple", advanced: "Advanced", advanced_day1_stop: "Advanced + Day1 3% Stop" } as const;
  const top = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm({ ...form, [key]: value });
  const param = <K extends keyof FormState["parameters"]>(key: K, value: FormState["parameters"][K]) => setForm({ ...form, parameters: { ...form.parameters, [key]: value } });
  const numberParam = (key: keyof FormState["parameters"]) => (event: React.ChangeEvent<HTMLInputElement>) => param(key, Number(event.target.value));
  const numeric = (value: number, onChange: React.ChangeEventHandler<HTMLInputElement>, decimal = true) => <input type="number" inputMode={decimal ? "decimal" : "numeric"} step={decimal ? "0.1" : "1"} className="input" value={value} onChange={onChange}/>;
  const runLabel = running ? progressStage : "Run Backtest";
  const useRecentTestRange = () => {
    const end = new Date();
    end.setHours(12, 0, 0, 0);
    end.setDate(end.getDate() - 1);
    while (end.getDay() === 0 || end.getDay() === 6) end.setDate(end.getDate() - 1);
    const start = new Date(end);
    let tradingDays = 1;
    while (tradingDays < 20) {
      start.setDate(start.getDate() - 1);
      if (start.getDay() !== 0 && start.getDay() !== 6) tradingDays += 1;
    }
    const localDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
    setForm({ ...form, start_date: localDate(start), end_date: localDate(end) });
  };

  return <>
    <aside className="settings-rail panel sticky top-3 max-h-[calc(100vh-24px)] w-[306px] shrink-0 overflow-y-auto p-3 scrollbar" aria-label={t("Backtest settings")}>
      <div className="mb-3 flex items-start justify-between px-1 pt-1">
        <div><p className="m-0 text-[10px] font-semibold uppercase tracking-[.16em] text-cyan-300">{t("Research setup")}</p><h2 className="mt-1 text-base font-semibold">{t("Strategy Settings")}</h2></div>
        <button className="rounded-md p-2 text-slate-400 hover:bg-slate-800 hover:text-white" title={t("Reset parameters")} onClick={() => location.reload()}><RotateCcw size={15}/></button>
      </div>
      <div className="grid gap-2">
        <Section title={t("Market")} hint={`${form.ticker} · ${t("Daily OHLC")}`} open>
          <Field label={t("Ticker")}><input className="input font-semibold uppercase" autoCapitalize="characters" value={form.ticker} onChange={e => top("ticker", e.target.value.toUpperCase())}/></Field>
          <Field label={t("Start date")}><input type="date" className="input" value={form.start_date} onChange={e => top("start_date", e.target.value)}/></Field>
          <Field label={t("End date")}><input type="date" className="input" value={form.end_date} onChange={e => top("end_date", e.target.value)}/></Field>
          <button type="button" onClick={useRecentTestRange} className="settings-wide rounded-md border border-cyan-400/30 bg-cyan-400/5 px-3 py-2 text-xs font-semibold text-cyan-300 hover:bg-cyan-400/10">{t("Use recent test range")}</button>
        </Section>
        <Section title={t("Strategy")} hint={t(strategyLabels[form.strategy])} open>
          <Field label={t("Strategy")} wide><div className="grid grid-cols-1 rounded-md border border-[#293a50] bg-[#0a111b] p-1">{(["simple", "advanced", "advanced_day1_stop"] as const).map(item => <button key={t(item)} onClick={() => top("strategy", item)} className={`rounded px-2 py-2 text-left text-xs font-semibold ${form.strategy === item ? "bg-cyan-400 text-slate-950" : "text-slate-400 hover:text-white"}`}>{t(strategyLabels[item])}</button>)}</div></Field>
          {(form.strategy === "simple" || form.strategy === "advanced") && <div className="settings-wide rounded-md border border-amber-400/25 bg-amber-400/5 p-2.5 text-[10px] leading-4 text-amber-100"><strong className="block text-amber-300">{t("Research baseline strategy")}</strong>{t("Historical research did not pass the strategy viability gate and does not imply suitability for real trading.")}</div>}
          <Field label={t("MA type")}><select className="input" value={form.parameters.ma_type} onChange={e => param("ma_type", e.target.value as "sma" | "ema")}><option value="sma">{t("SMA")}</option><option value="ema">{t("EMA")}</option></select></Field>
          <p className="settings-wide m-0 text-[10px] leading-4 text-slate-500">{t("ma.help")}</p><Field label={t("MA period")}>{numeric(form.parameters.ma_period, numberParam("ma_period"), false)}</Field>
        </Section>
        <Section title={t("Entry")} hint={messages.entryHint(form.parameters.breakout_trigger_pct, form.parameters.entry_stop_pct)} open>
          <Field label={t("Breakout trigger %")}>{numeric(form.parameters.breakout_trigger_pct, numberParam("breakout_trigger_pct"))}</Field>
          <Field label={t("Entry stop %")}>{numeric(form.parameters.entry_stop_pct, numberParam("entry_stop_pct"))}</Field>
          {form.strategy === "simple" && <Field label={t("Exit below MA %")} wide>{numeric(form.parameters.exit_below_ma_pct, numberParam("exit_below_ma_pct"))}</Field>}
        </Section>
        {isAdvanced && <>
          <Section title={t("Validation")} hint={t("Day 1 volume · Day 2 close")}><Field label={t("Volume increase %")} wide>{numeric(form.parameters.volume_increase_pct, numberParam("volume_increase_pct"))}</Field></Section>
          <Section title={t("Risk Control")} hint={form.strategy === "advanced_day1_stop" ? messages.riskHint(form.parameters.day1_stop_pct, form.parameters.ma_risk_pct) : `${t("MA")} −${form.parameters.ma_risk_pct}%`}>
            {form.strategy === "advanced_day1_stop" && <Field label={t("Day 1 Stop Below MA %")} wide>{numeric(form.parameters.day1_stop_pct, numberParam("day1_stop_pct"))}</Field>}
            <Field label={t("MA risk threshold %")} wide>{numeric(form.parameters.ma_risk_pct, numberParam("ma_risk_pct"))}</Field>
          </Section>
          <Section title={t("Take Profit")} hint={messages.firstHint(form.parameters.first_tp_pct)}><Field label={t("First take profit %")} wide>{numeric(form.parameters.first_tp_pct, numberParam("first_tp_pct"))}</Field></Section>
          <Section title={t("Extreme Take Profit")} hint={`${form.parameters.bias_sigma_multiple}σ · ${form.parameters.atr_multiple}×ATR`}>
            <Field label={t("Bias lookback")}>{numeric(form.parameters.bias_lookback, numberParam("bias_lookback"), false)}</Field>
            <Field label={t("Bias sigma multiple")}>{numeric(form.parameters.bias_sigma_multiple, numberParam("bias_sigma_multiple"))}</Field>
            <Field label={t("ATR period")}>{numeric(form.parameters.atr_period, numberParam("atr_period"), false)}</Field>
            <Field label={t("ATR multiple")}>{numeric(form.parameters.atr_multiple, numberParam("atr_multiple"))}</Field>
            <Field label={t("Extreme TP % Q0")}>{numeric(form.parameters.extreme_tp_pct_q0, numberParam("extreme_tp_pct_q0"))}</Field>
            <Field label={t("Maximum TP count")}>{numeric(form.parameters.max_extreme_tp_count, numberParam("max_extreme_tp_count"), false)}</Field>
            <Field label={t("Minimum position % Q0")} wide>{numeric(form.parameters.minimum_position_pct_q0, numberParam("minimum_position_pct_q0"))}</Field>
          </Section>
        </>}
        <Section title={t("Backtest Settings")} hint={`${formatMoney(form.initial_capital)} · ${form.position_size_pct}%`}>
          <Field label={t("Market data provider")} wide><select className="input" value={form.market_data_provider} onChange={e => top("market_data_provider", e.target.value as FormState["market_data_provider"])}><option value="auto">{t("Auto (cache → Yahoo → Stooq)")}</option><option value="yahoo">{t("Yahoo Finance (with fallback)")}</option><option value="alternative">{t("Alternative (Stooq)")}</option></select></Field>
          <p className="settings-wide m-0 text-[10px] leading-4 text-slate-500">{t("Complete local Parquet cache always wins. Yahoo and Stooq caches are isolated because their adjustment policies may differ.")}</p>
          <Field label={t("Daily Intrabar Assumption")} wide><select className="input" value={form.execution_policy} onChange={e => top("execution_policy", e.target.value as FormState["execution_policy"])}><option value="conservative">{t("Conservative (default)")}</option><option value="ohlc_heuristic">{t("OHLC Heuristic")}</option><option value="favorable">{t("Favorable")}</option></select></Field>
          <p className="settings-wide m-0 text-[10px] leading-4 text-slate-500">{t("Daily OHLC does not reveal whether the day's high or low occurred first. This setting controls how ambiguous same-day events are ordered.")} {t(`policy.${form.execution_policy}`)}</p>
          <Field label={t("Initial capital")}><input type="number" inputMode="decimal" className="input" value={form.initial_capital} onChange={e => top("initial_capital", Number(e.target.value))}/></Field>
          <Field label={t("Position size %")}><input type="number" inputMode="decimal" className="input" value={form.position_size_pct} onChange={e => top("position_size_pct", Number(e.target.value))}/></Field>
          <label className="settings-wide flex min-h-10 items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={form.force_close_at_end} onChange={e => top("force_close_at_end", e.target.checked)}/>{t("Force close at end")}</label>
        </Section>
        <Section title={t("Trading Costs")} hint={`${form.commission_pct}% + ${form.slippage_pct}%`}>
          <Field label={t("Commission %")}><input type="number" inputMode="decimal" step="0.01" className="input" value={form.commission_pct} onChange={e => top("commission_pct", Number(e.target.value))}/></Field>
          <Field label={t("Slippage %")}><input type="number" inputMode="decimal" step="0.01" className="input" value={form.slippage_pct} onChange={e => top("slippage_pct", Number(e.target.value))}/></Field>
        </Section>
        <button disabled={running} onClick={onRun} className="desktop-run-button mt-1 flex min-h-11 items-center justify-center gap-2 rounded-md bg-cyan-400 px-4 font-bold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-wait disabled:opacity-60"><Play size={16} fill="currentColor"/>{t(runLabel)}</button>
        <p className="m-0 py-1 text-center text-[10px] leading-relaxed text-slate-500">{t("Execution Model: Daily OHLC")} · {t(form.execution_policy)}</p>
      </div>
    </aside>
    <div className="mobile-run-bar" role="region" aria-label={t("Run backtest action")}><button disabled={running} aria-busy={running} onClick={onRun}><Play size={17} fill="currentColor"/>{t(runLabel)}</button></div>
  </>;
}
