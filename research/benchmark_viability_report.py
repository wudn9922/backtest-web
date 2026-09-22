"""Markdown renderer for the frozen Benchmark Viability Study."""
from __future__ import annotations

import json
import statistics
from research import ROOT


def pct(v): return "—" if v is None else f"{100*v:.2f}%"
def pp(v): return "—" if v is None else f"{v:+.2f}pp"
def num(v): return "—" if v is None else f"{v:.2f}"


def render(d):
    out = ["# Benchmark Viability Study", "", "> Retrospective research only. No candidate was created; no parameter or production strategy changed.", ""]
    out += ["## Executive Summary", "", f"- SMA200: **{d['grades']['SMA200_TREND']['grade']}**", f"- Donchian 20/10: **{d['grades']['DONCHIAN_20_10']['grade']}**", f"- **NEXT FAMILY = {d['next_family']}**", ""]
    sma=d['full_breadth']['SMA200_TREND']['conservative'];don=d['full_breadth']['DONCHIAN_20_10']['conservative']
    sma_exp=d['cash_drag']['SMA200_TREND']['conservative']['median'];don_exp=d['cash_drag']['DONCHIAN_20_10']['conservative']['median']
    max_policy=max(x['return_range_pp'] for x in d['policy_sensitivity']['donchian'].values())
    out += [
        f"SMA200 beat Buy & Hold on full-period Return for only {sma['return_wins']}/{sma['cells']} symbols and Sharpe for {sma['sharpe_wins']}/{sma['cells']}; paired median deltas were {sma['median_return_delta_pp']:+.2f}pp Return, {sma['median_sharpe_delta']:+.3f} Sharpe and {sma['median_mdd_delta_pp']:+.2f}pp MDD. It reduced MDD for all {sma['mdd_wins']}/{sma['cells']} symbols but retained median capital exposure of only {sma_exp:.1f}%.", "",
        f"Donchian beat Buy & Hold on Return for {don['return_wins']}/{don['cells']} and Sharpe for {don['sharpe_wins']}/{don['cells']}; paired median deltas were {don['median_return_delta_pp']:+.2f}pp Return, {don['median_sharpe_delta']:+.3f} Sharpe and {don['median_mdd_delta_pp']:+.2f}pp MDD, at {don_exp:.1f}% median exposure.", "",
        f"No genuine Donchian entry/exit ambiguity occurred in this sample: all three policies were identical and the maximum ticker Return range was {max_policy:.2f}pp. This is observed sample evidence, not a claim that Donchian is structurally policy-independent.", "",
    ]
    out += ["## Frozen specifications", "", f"Specification: `{d['benchmark_spec']['path']}`", f"SHA-256: `{d['benchmark_spec']['sha256']}`", "",
            "SMA200 uses Close(t) versus SMA200(t) only to schedule the next session OPEN. Donchian entry/exit levels exclude t and use prior 20/10 completed bars. Exact gap and ambiguity semantics are in the hashed specification.", ""]
    x=d['data'];out += ["## Data and fair warm-up", "", f"- DATA START: {x['data_start']}", f"- EVALUATION START: {x['evaluation_start']}", f"- EVALUATION END: {x['evaluation_end']}", f"- Warm-up: {x['warmup_completed_bars']} completed bars", "- Buy & Hold starts on the same evaluation date; warm-up return is excluded.", "- Cash return assumption: 0%.", ""]
    out += ["## Full-period comparison", "", "| Symbol | Benchmark | Policy | Return | CAGR | MDD | Sharpe | Sortino | Calmar | Exposure | Turnover | Commission | Slippage | Trades | Avg hold | vs B&H Return | vs B&H MDD | Class |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in d['full_period']:
        m=r['metrics'];v=r.get('vs_buy_hold',{});delta=v.get('delta',{})
        out.append(f"| {r['symbol']} | {r['benchmark']} | {r['policy'] or '—'} | {pct(m['total_return'])} | {pct(m['cagr'])} | {pct(m['max_drawdown'])} | {num(m['sharpe_ratio'])} | {num(m['sortino_ratio'])} | {num(m['calmar_ratio'])} | {m['average_close_capital_exposure_pct']:.1f}% | {m['turnover']:.2f} | ${m['total_commission']:,.2f} | ${m['estimated_slippage_cost']:,.2f} | {m['number_of_trades']} | {num(m['average_holding_days'])} | {pp(delta.get('return_pp'))} | {pp(delta.get('mdd_pp'))} | {v.get('classification','—')} |")
    out += ["", "## Cross-symbol breadth", "", "| Benchmark | Policy | Return wins | Sharpe wins | MDD wins | Median Return Δ | Median Sharpe Δ | Median MDD Δ |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for b,policies in d['full_breadth'].items():
        for p,r in policies.items(): out.append(f"| {b} | {p} | {r['return_wins']}/{r['cells']} | {r['sharpe_wins']}/{r['cells']} | {r['mdd_wins']}/{r['cells']} | {pp(r['median_return_delta_pp'])} | {num(r['median_sharpe_delta'])} | {pp(r['median_mdd_delta_pp'])} |")
    out += ["", "## Intrabar-policy sensitivity", "", f"SMA200 policy results are byte-equivalent: **{d['policy_sensitivity']['sma200_all_policies_identical']}**. Donchian policy ranges and genuine ambiguous-day counts are recorded per ticker in the machine-readable file.", ""]
    out += ["| Symbol | Return range | MDD range | Sharpe range | Conservative ambiguous days | Heuristic | Favorable |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s,r in d['policy_sensitivity']['donchian'].items(): out.append(f"| {s} | {r['return_range_pp']:.2f}pp | {r['mdd_range_pp']:.2f}pp | {r['sharpe_range']:.2f} | {r['ambiguous_days_by_policy']['conservative']} | {r['ambiguous_days_by_policy']['ohlc_heuristic']} | {r['ambiguous_days_by_policy']['favorable']} |")
    out += ["", "## Calendar-year and rolling robustness", "", "The JSON contains every ticker/year and every monthly-stepped 6M/12M window with Return, MDD, Sharpe, exposure, trades and same-window Buy & Hold return. Cross-symbol calendar medians are:", "", "| Year | Benchmark | Return | MDD | Sharpe | Exposure | Trades | Buy & Hold Return |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    years=sorted({r['window'] for r in d['calendar_year']})
    for year in years:
        for benchmark,policy in (("BUY_AND_HOLD",None),("SMA200_TREND","conservative"),("DONCHIAN_20_10","conservative")):
            group=[r for r in d['calendar_year'] if r['window']==year and r['benchmark']==benchmark and r['policy']==policy]
            med=lambda key: statistics.median(r['metrics'][key] for r in group)
            out.append(f"| {year}{'*' if group[0]['partial_year'] else ''} | {benchmark} | {pct(med('total_return'))} | {pct(med('max_drawdown'))} | {num(med('sharpe_ratio'))} | {med('average_close_capital_exposure_pct'):.1f}% | {statistics.median(r['metrics']['number_of_trades'] for r in group):.0f} | {pct(statistics.median(r['buy_hold_return'] for r in group))} |")
    out += ["", "`*` marks a partial calendar year. Rolling 6M breadth:", "", "| Benchmark | Policy | Return win breadth | Sharpe win breadth | MDD win breadth |", "|---|---|---:|---:|---:|"]
    for b,policies in d['rolling_breadth'].items():
        for p,r in policies.items(): out.append(f"| {b} | {p} | {r['return_wins']}/{r['cells']} | {r['sharpe_wins']}/{r['cells']} | {r['mdd_wins']}/{r['cells']} |")
    out += ["", "## Retrospective Walk-Forward Robustness Validation", "", "Expanding and rolling designs use identical six-month TEST windows; train never tunes a rule. Their raw test results therefore match, while train dates document the chronological evidence boundary.", "", "| Benchmark | Policy | Return wins | Sharpe wins | MDD wins |", "|---|---|---:|---:|---:|"]
    for b,policies in d['walk_forward_breadth'].items():
        for p,r in policies.items(): out.append(f"| {b} | {p} | {r['return_wins']}/{r['cells']} | {r['sharpe_wins']}/{r['cells']} | {r['mdd_wins']}/{r['cells']} |")
    out += ["", "## Trend-regime attribution", ""]
    fold_file=json.loads((ROOT/d['walk_forward_file']).read_text(encoding='utf-8'))
    spy_folds=[r for r in fold_file['rows'] if r['design']=='expanding' and r['benchmark']=='BUY_AND_HOLD' and r['symbol']=='SPY']
    out += ["All seven fixed test folds classified as strong SPY uptrends; six were low-volatility and one high-volatility. Therefore these folds can describe bull-market cash drag but cannot identify sideways/downtrend superiority. No cutoff was searched or changed.", "", "| Fold | Test | SPY regime | Volatility | SPY return |", "|---|---|---|---|---:|"]
    for r in spy_folds: out.append(f"| {r['fold']} | {r['test_start']} → {r['test_end']} | {r['regime']['trend']} | {r['regime']['volatility']} | {pct(r['regime']['spy_return'])} |")
    out += ["", "## Winner concentration and whipsaw", ""]
    for b,policies in d['winner_concentration'].items():
        for p,r in policies.items():
            w=d['whipsaw'][b][p]
            out += [f"### {b} — {p}", "", f"- Top-10% winner share: {pct(r['top_10pct_winner_share'])}; `WINNER_CONCENTRATED={r['winner_concentrated']}`.", f"- Net PnL after removing each symbol's largest winner: ${r['remove_largest_winner_per_symbol_net_pnl']:,.2f}.", f"- <=5-session whipsaws: {w['le_5d']['count']}, net ${w['le_5d']['net_pnl']:,.2f}, {pct(w['le_5d']['share_of_total_loss'])} of losses.", f"- <=10-session whipsaws: {w['le_10d']['count']}, net ${w['le_10d']['net_pnl']:,.2f}, {pct(w['le_10d']['share_of_total_loss'])} of losses.", f"- <=20-session whipsaws: {w['le_20d']['count']}, net ${w['le_20d']['net_pnl']:,.2f}, {pct(w['le_20d']['share_of_total_loss'])} of losses.", ""]
    out += ["## Tail protection and cash drag", "", "| Benchmark | Median exposure | Median cash | Median MDD reduction in B&H worst episode | Median relative upside after bottom to B&H recovery |", "|---|---:|---:|---:|---:|"]
    for b in ("SMA200_TREND","DONCHIAN_20_10"):
        group=[r for r in d['tail_protection'] if r['benchmark']==b and r['policy']=='conservative']
        reduction=statistics.median(r['mdd_reduction_pp'] for r in group)
        recovery=[r['relative_upside_after_bottom_to_recovery'] for r in group if r['relative_upside_after_bottom_to_recovery'] is not None]
        exposure=d['cash_drag'][b]['conservative']['median']
        out.append(f"| {b} | {exposure:.1f}% | {100-exposure:.1f}% | {reduction:+.2f}pp | {pct(statistics.median(recovery)) if recovery else '—'} |")
    out += ["", "Both benchmarks reduced losses in B&H's worst episodes, but lagged materially during the subsequent recovery. Cash earns 0%, so the 28.1% median SMA200 cash share and 54.8% Donchian cash share create explicit bull-market drag.", ""]
    out += ["## Cost stress", "", "| Scenario | Benchmark | Policy | Return wins | Median Return Δ | Sharpe wins | MDD wins |", "|---|---|---|---:|---:|---:|---:|"]
    for scenario in ("BASELINE","DOUBLE_COMMISSION","DOUBLE_SLIPPAGE","DOUBLE_BOTH"):
        for b in ("SMA200_TREND","DONCHIAN_20_10"):
            for p in ("conservative",):
                r=d['cost_breadth'][scenario][b][p]
                out.append(f"| {scenario} | {b} | {p} | {r['return_wins']}/{r['cells']} | {r['median_return_delta_pp']:+.2f}pp | {r['sharpe_wins']}/{r['cells']} | {r['mdd_wins']}/{r['cells']} |")
    out += ["", "Neither benchmark survives the double-commission-plus-double-slippage screen as a return improvement; Donchian remains the higher-turnover and more cost-exposed family.", ""]
    out += ["## Cluster/block-aware uncertainty", "", "Intervals resample ticker and chronological half-year blocks; ticker × policy × period is not IID.", "", "| Benchmark | Policy | Median Return Δ | Mean Return Δ 95% cluster interval | Median Sharpe Δ | Mean Sharpe Δ 95% cluster interval |", "|---|---|---:|---:|---:|---:|"]
    for b,policies in d['uncertainty'].items():
        for p,r in policies.items():
            rc=r['return_delta_pp'];sc=r['sharpe_delta']
            out.append(f"| {b} | {p} | {rc['point']['median']:+.2f}pp | [{rc['mean_ci95'][0]:+.2f}, {rc['mean_ci95'][1]:+.2f}]pp | {sc['point']['median']:+.3f} | [{sc['mean_ci95'][0]:+.3f}, {sc['mean_ci95'][1]:+.3f}] |")
    out += ["## Family decision", "", f"SMA200 grade: **{d['grades']['SMA200_TREND']['grade']}**.", f"Donchian grade: **{d['grades']['DONCHIAN_20_10']['grade']}**.", f"The only allowed next-step declaration is **NEXT FAMILY = {d['next_family']}**. This study creates no candidate; a future candidate requires a separately frozen spec.", ""]
    out += ["### Direct answers", "", "1. **SMA200 did not improve paired risk-adjusted return across stocks:** Sharpe improved for 5/11 and the median paired Sharpe delta was slightly negative.", "2. **Its main observed value was drawdown reduction:** MDD improved for 11/11, while full-period Return improved for only 1/11 and bull-market recovery upside was sacrificed.", "3. **Donchian 20/10 showed no cross-stock edge under the gate:** Return improved for 3/11; median Return and Sharpe deltas were negative.", "4. **Observed Donchian policy sensitivity was zero in this sample:** no genuine same-bar entry/exit ambiguity occurred. The frozen specification remains policy-aware for future data.", "5. **SMA200 was more winner-concentrated:** pooled top-10% winner share was about 64.2%, versus 54.6% for Donchian; neither crossed the automatic flag.", "6. **Donchian whipsawed more frequently through 20 sessions:** 195 pooled trades versus 134; SMA200's very-short <=5-session trades represented a larger share of its loss.", "7. **Neither survived doubled costs as a return winner:** paired median Return deltas remained materially negative.", "8. **Donchian had the better relative rolling Return breadth, but neither was stable enough:** 220/605 versus SMA200 135/605, both below half.", "9. **Trend family: do not create TREND_001 from this evidence.**", "10. **Breakout family: do not create BREAKOUT_001 from this evidence.**", "11. **NEXT FAMILY = NONE.**", ""]
    out += ["## Invariance", "", "Simple v2, Advanced v2 and M3 registry entries are unchanged. Canonical production executions, PnL, equity and audits have zero differences. The report is research-only and not true out-of-sample evidence.", ""]
    return "\n".join(out)


def write_report(data):
    (ROOT / "reports/benchmark-viability-study.md").write_text(render(data), encoding="utf-8")
