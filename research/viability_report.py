"""Traditional-Chinese Markdown renderer for the Simple-v2 viability gate."""
from __future__ import annotations

import json
from research import ROOT
from research.viability_design import POLICIES, SYMBOLS

P = {"conservative": "保守", "ohlc_heuristic": "OHLC 推估", "favorable": "有利"}


def n(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def pct(value, digits=2):
    return "—" if value is None else f"{100 * value:,.{digits}f}%"


def md(headers, rows):
    clean = lambda value: str(value).replace("|", "／").replace("\n", " ")
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(clean(v) for v in row) + " |" for row in rows])


def render(data):
    lines = []
    def add(text=""):
        lines.extend([text, ""])
    breadth = data["full_period_breadth"]
    decision = data["decision"]
    ambiguity = data["ambiguity"]
    entry = data["entry_zone"]["summary"]
    costs = data["cost_robustness"]
    cons_concentration = data["winner_concentration"]["pooled_conservative"]

    def breadth_answer(comparator):
        return "；".join(f"{P[p]} Return {breadth[comparator][p]['return_improved']}/11、Sharpe {breadth[comparator][p]['sharpe_improved']}/11、median ΔReturn {n(breadth[comparator][p]['return_delta_pp']['median'])}pp" for p in POLICIES)

    valid_edge = {h: entry["valid_vs_unconditional"][h]["mean_difference"] for h in ("5", "10", "20", "40", "60")}
    valid_ci = {h: entry["valid_vs_unconditional"][h]["mean_difference_ci95"] for h in valid_edge}
    edge_support = sum(valid_edge[h] is not None and valid_edge[h] > 0 and valid_ci[h] and valid_ci[h][0] > 0 for h in valid_edge)
    missed = {h: entry["valid_vs_missed"][h]["mean_difference"] for h in ("5", "10", "20", "40")}
    worst_cost = costs["DOUBLE_BOTH"]["breadth"]
    stress_support = sum(all(worst_cost[c][p]["return_delta_pp"]["median"] > 0 for c in ("ADVANCED_V2", "BUY_AND_HOLD")) for p in POLICIES)
    mega_remaining = cons_concentration["without_nvda_meta_tsla_net_pnl"]
    freeze = decision["classification"] == "STRONG RETROSPECTIVE EVIDENCE — FREEZE FOR FORWARD TEST"

    add("# Simple Strategy Version 2 — Strategy Viability Gate")
    add("研究日期：2026-09-05。本報告是固定 production Simple v2／Advanced v2 的回溯研究，不是 true out-of-sample，也不是 production-ready 宣告。沒有調參、parameter sweep、新策略條件、v3、strategy mutation 或 history/audit 寫入；cash return 固定為 0。")
    add("## 1. Executive Summary 與決策問題")
    add(f"最終 evidence grade：**{decision['classification']}**。" +
        ("依事前門檻，值得把現行 Simple v2 原封不動 freeze 後進入真正 forward test；這不等於可上線交易。" if freeze else "依事前門檻，目前不應把它標成已具 strong evidence；production semantics 保持原狀。"))
    add(md(["問題", "資料答案"], [
        ["1. Simple 跨股票 outperform Advanced？", breadth_answer("ADVANCED_V2")],
        ["2. Simple 跨股票 outperform Buy & Hold？", breadth_answer("BUY_AND_HOLD")],
        ["3. 優勢來源", f"Entry Zone valid-vs-all-day 的 5/10/20/40/60D mean edge 為 " + "/".join(n(100*valid_edge[h]) if valid_edge[h] is not None else "—" for h in valid_edge) + f"pp；{edge_support}/5 horizons 的 block-bootstrap 95% interval 全在 0 上方。完整 Entry/Exit、winner retention、exposure 與集中度拆解見第 8～10 節。"],
        ["4. 高 MDD 是否值得？", "不可只由高報酬回答；第 4、11 節同列 Sharpe/Calmar、MDD、曝險與 Advanced 同 episode 的 loss avoided。Evidence gate 對風險設獨立限制。"],
        ["5. Entry Zone v2 selection edge？", f"依事前 descriptive 定義，{'有較一致的正向證據' if edge_support >= 3 else '證據不足或不一致'}；valid signals={entry['counts']['VALID_ENTRY']:,}，但訊號高度重疊，不能當獨立交易或 portfolio。"],
        ["6. ENTRY_ZONE_MISSED 是否避免追高？", "Valid-minus-missed 5/10/20/40D mean 為 " + "/".join(n(100*missed[h]) for h in missed) + "pp；正值表示 valid 後續較佳、負值表示被拒絕的 gap 反而較強。這是既有規則稽核，不會回頭改門檻。"],
        ["7. Daily OHLC ambiguity 改變結論？", f"分類 **{ambiguity['classification']}**；受影響/分歧 anchors {ambiguity['affected_entries']}，三 policy cross-symbol median Simple−B&H Return = " + "/".join(n(ambiguity['policy_median_simple_minus_buy_hold_return_pp'][p]) for p in POLICIES) + "pp。"],
        ["8. 成本壓力後維持？", f"2× commission+2× slippage 下，有 {stress_support}/3 policies 對 Advanced 與 B&H 的 median Return delta 同時為正。"],
        ["9. 依賴 NVDA/META/TSLA 或少數 winner？", f"保守 pooled 移除 NVDA/META/TSLA 後 net PnL=${n(mega_remaining)}；移除每個 symbol 最大 winner 後=${n(cons_concentration['remove_each_symbol_largest_winner_net_pnl'])}。Top-share 詳見第 10 節。這是 11 個各自 $100k sleeve 的描述性美元總和。"],
        ["10. 最終 grade", decision["classification"]],
        ["11. Freeze 進真正 forward test？", "是；只 freeze 未修改的 Simple v2。" if freeze else "否；目前事前 gate 未達 strong retrospective evidence。"],
    ]))

    add("## 2. Freeze、資料與 benchmark 定義")
    add("Simple v2 與 Advanced v2 都使用 production Strategy Version 2。Entry Zone、MA(t-1)、成本、slippage、whole shares、Daily OHLC policy 全未改。Buy & Hold 在每個 window 首個可交易日 Open 以同一 position allocation 及成本買入，最後一日 Close 賣出；Entry Zone Hold 用正式 v2 第一個有效 entry，之後只在 window 末出場。後者及 20/40/60D signal holds 都只是 research benchmark。")
    add(md(["Symbol", "Provider", "Adjustment", "Coverage", "Bars", "Warm-up", "OHLC hash"], [[
        r["symbol"], r["provider"], r["adjustment_mode"], f"{r['first_date']}～{r['last_date']}", r["bars"], r["warmup_bars"], r["ohlcv_sha256"][:12]
    ] for r in data["validation"]["data_manifest"]]))
    add("Yahoo metadata 的 legacy label 是 `adjusted_for_splits`；實際 contract 是 adjusted_close/close 套用 OHLC、volume unchanged。11 symbols 的 session calendar 在 FULL/A/B 都完全一致；不混入其他 adjustment basis。")
    add(md(["Canonical", "ID", "Return", "CAGR", "MDD", "Sharpe", "Positions"], [[
        key, value["backtest_id"], pct(value["summary"]["total_return"]), pct(value["summary"]["cagr"]),
        pct(value["summary"]["max_drawdown"]), n(value["summary"]["sharpe_ratio"]), value["summary"]["number_of_positions"]
    ] for key, value in data["canonical"].items()]))

    add("## 3. Full-period metrics（2021-09-01～2026-09-01）")
    records = data["portfolio"]
    full = [r for r in records if r["period"] == "FULL"]
    # Keep average invested capital distinct from sessions with any exposure.
    table_rows = []
    for symbol in SYMBOLS:
        for policy in POLICIES:
            for strategy in ("SIMPLE_V2", "ADVANCED_V2"):
                r = next(x for x in full if x["symbol"] == symbol and x["policy"] == policy and x["strategy"] == strategy)
                m = r["metrics"]
                table_rows.append([symbol, P[policy], strategy, pct(m["total_return"]), pct(m["cagr"]), pct(m["max_drawdown"]), n(m["sharpe_ratio"]), n(m["sortino_ratio"]), n(m["calmar_ratio"]), n(m["average_close_capital_exposure_pct"]) + "%", n(m["exposure_pct"]) + "%", m["number_of_positions"], n(m["turnover"])])
        for strategy in ("BUY_AND_HOLD", "ENTRY_ZONE_HOLD"):
            r = next(x for x in full if x["symbol"] == symbol and x["strategy"] == strategy)
            m = r["metrics"]
            table_rows.append([symbol, "不適用", strategy, pct(m["total_return"]), pct(m["cagr"]), pct(m["max_drawdown"]), n(m["sharpe_ratio"]), n(m["sortino_ratio"]), n(m["calmar_ratio"]), n(m["average_close_capital_exposure_pct"]) + "%", n(m["exposure_pct"]) + "%", m["number_of_positions"], n(m["turnover"])])
    add(md(["Symbol", "Policy", "Strategy", "Return", "CAGR", "MDD", "Sharpe", "Sortino", "Calmar", "Avg stock exposure", "Time in market", "Pos", "Turnover"], table_rows))
    add("Win rate、Profit Factor、平均持有日、commission、slippage、executions/equity hashes 均在 JSON `portfolio`。Buy & Hold 的 Win/PF 只描述單一完整持有 lifecycle，不作策略勝率推論。")

    add("## 4. Simple vs Advanced / Buy & Hold breadth")
    add(md(["Comparator", "Policy", "Return +", "Sharpe +", "MDD +", "Median ΔReturn pp", "Median ΔSharpe", "Median ΔMDD pp", "Median ΔCalmar"], [[
        comparator, P[policy], x["return_improved"], x["sharpe_improved"], x["mdd_improved"],
        n(x["return_delta_pp"]["median"]), n(x["sharpe_delta"]["median"]), n(x["mdd_delta_pp"]["median"]), n(x["calmar_delta"]["median"])
    ] for comparator in ("ADVANCED_V2", "BUY_AND_HOLD") for policy, x in breadth[comparator].items()]))
    labels = [r for r in data["comparisons"] if r["period"] == "FULL" and r["comparator"] == "BUY_AND_HOLD"]
    add(md(["Symbol", "Conservative", "Heuristic", "Favorable"], [[s] + [next(r["label"] for r in labels if r["symbol"] == s and r["policy"] == p) for p in POLICIES] for s in SYMBOLS]))
    add("ΔMDD 為 Simple minus comparator；正值代表較淺、負值代表較深。Status 互斥：先檢查完整 risk-adjusted win，再 return win，再 1pp/0.10 tolerance draw，其他為 loss。")

    add("## 5. Exposure-normalized interpretation")
    add("`return / average exposure` 與 `abs(drawdown) / average exposure` 只為描述，不是正式績效指標；曝險會隨時間改變，不能視為 leverage-normalized backtest。Cash return=0。")
    exp = [r for r in data["exposure_normalized"] if r["policy"] in (None, "conservative")]
    add(md(["Symbol", "Strategy", "Avg exposure", "Cash", "Return/exposure", "Abs.MDD/exposure"], [[
        r["symbol"], r["strategy"], n(r["metrics"]["average_close_capital_exposure_pct"]) + "%", n(r["metrics"]["cash_pct"]) + "%",
        n(r["normalized"]["return_per_average_exposure"]), n(r["normalized"]["absolute_drawdown_per_average_exposure"])
    ] for r in exp]))

    add("## 6. Cross-period robustness")
    add(md(["Period", "Policy", "Comparator", "Return +/11", "Sharpe +/11", "MDD +/11", "Median ΔReturn pp", "Median ΔSharpe", "Median ΔMDD pp"], [[
        r["period"], P[r["policy"]], r["comparator"], r["return_improved"], r["sharpe_improved"], r["mdd_improved"],
        n(r["median_return_delta_pp"]), n(r["median_sharpe_delta"]), n(r["median_mdd_delta_pp"])
    ] for r in data["cross_period"]]))

    add("## 7. Retrospective walk-forward（不是 true OOS）")
    add("每 fold 以 flat、fresh canonical capital 開始；train 只累積當時可見 evidence，不調參。Expanding 與 Rolling 的 raw test window 相同，故 test 數字相同；差別僅在 train gate。短期 CAGR 只為欄位一致，不作主要推論。")
    add(md(["Fold", "Policy", "Return + vs Adv", "Return + vs B&H", "Sharpe + vs Adv/B&H", "MDD + vs Adv/B&H", "Median ΔReturn Adv/B&H pp"], [[
        r["fold"], P[r["policy"]], r["vs_advanced_return_improved"], r["vs_buy_hold_return_improved"],
        f"{r['vs_advanced_sharpe_improved']}/{r['vs_buy_hold_sharpe_improved']}", f"{r['vs_advanced_mdd_improved']}/{r['vs_buy_hold_mdd_improved']}",
        f"{n(r['median_return_delta_vs_advanced_pp'])}/{n(r['median_return_delta_vs_buy_hold_pp'])}"
    ] for r in data["walk_forward"]["fold_breadth"]]))
    add(md(["Design", "Fold", "Gate", "Passed policies"], [[design, fold, gate["composite"]["status"], ", ".join(P[p] for p in gate["composite"]["passed_policies"]) or "無"] for design, fs in data["walk_forward"]["train_gates"].items() for fold, gate in fs.items()]))
    add("Machine-readable 396 rows（2 designs × 6 folds × 11 symbols × 3 policies）在 `data/simple-v2-walk-forward-folds.json`。相同 test 不當成兩份證據；breadth/uncertainty 只用 expanding 一份。")

    add("## 8. Daily OHLC ambiguity 與 ambiguity-free cohort")
    add(f"結論：**{ambiguity['classification']}**。Genuine ambiguity 與任何三-policy execution divergence 都從 ambiguity-free matched cohort 排除；沒有把所有 engine flag 自動當 genuine，也沒有把 `Open<Entry` 錯認為 Low 必定先發生。")
    add(md(["Symbol", "Cons days/positions", "Heuristic", "Favorable"], [[s] + [f"{ambiguity['by_symbol'][s][p]['ambiguous_days']}/{ambiguity['by_symbol'][s][p]['ambiguous_positions']}" for p in POLICIES] for s in SYMBOLS]))
    clean = ambiguity["ambiguity_free_matched"]
    add(f"Ambiguity-free、policy-invariant matched entries={clean['entries']}；Simple−Advanced matched net PnL mean/median=${n(clean['simple_minus_advanced_net_pnl']['mean'])}/${n(clean['simple_minus_advanced_net_pnl']['median'])}；holding-days delta mean={n(clean['holding_days_delta']['mean'])}。完整 rows 在 JSON。")
    add(f"受影響 entries 的 Favorable−Conservative Simple PnL：mean=${n(ambiguity['cost_favorable_minus_conservative']['mean'])}、median=${n(ambiguity['cost_favorable_minus_conservative']['median'])}、sum=${n(ambiguity['cost_favorable_minus_conservative']['sum'])}。")
    entry_amb = ambiguity["entry_day_ambiguity"]
    add(f"其中 Simple `ENTRY_THEN_STOP_AMBIGUITY` anchors={entry_amb['entries']}；Favorable−Conservative PnL mean/median/sum=${n(entry_amb['favorable_minus_conservative_pnl']['mean'])}/${n(entry_amb['favorable_minus_conservative_pnl']['median'])}/${n(entry_amb['favorable_minus_conservative_pnl']['sum'])}。這是 entry-day uncertainty 的獨立量化。")

    add("## 9. Entry Zone edge 與不追 gap")
    add(md(["Horizon", "Valid n/mean/median", "All-day n/mean/median", "Mean edge", "Block CI95"], [[
        h + "D", f"{entry['valid_vs_unconditional'][h]['selected']['n']}/{pct(entry['valid_vs_unconditional'][h]['selected']['mean'])}/{pct(entry['valid_vs_unconditional'][h]['selected']['median'])}",
        f"{entry['valid_vs_unconditional'][h]['unconditional']['n']}/{pct(entry['valid_vs_unconditional'][h]['unconditional']['mean'])}/{pct(entry['valid_vs_unconditional'][h]['unconditional']['median'])}",
        n(100 * entry['valid_vs_unconditional'][h]['mean_difference']) + "pp", f"[{n(100*entry['valid_vs_unconditional'][h]['mean_difference_ci95'][0])}, {n(100*entry['valid_vs_unconditional'][h]['mean_difference_ci95'][1])}]pp"
    ] for h in ("5", "10", "20", "40", "60")]))
    add(md(["Horizon", "Valid mean", "Missed mean", "Valid−missed"], [[h + "D", pct(entry["valid_vs_missed"][h]["valid"]["mean"]), pct(entry["valid_vs_missed"][h]["missed"]["mean"]), n(100*entry["valid_vs_missed"][h]["mean_difference"]) + "pp"] for h in ("5", "10", "20", "40")]))
    add("Forward return 從 signal-day Open 到第 N 個 subsequent trading-session Close；另存從 actual EntryLevel 與含成本、整股、固定 20/40/60D 的 returns。Signal 可以重疊，block bootstrap 以 ticker×半年整塊重抽，不是 iid trades。")

    add("## 10. Simple exit attribution 與 winner concentration")
    for policy in POLICIES:
        add(f"### {P[policy]}")
        add(md(["Exit", "Events", "PnL mean/median/sum", "MFE", "MAE", "5/10/20/40D post-close median"], [[reason, x["events"], f"${n(x['net_pnl']['mean'])}/${n(x['net_pnl']['median'])}/${n(x['net_pnl']['sum'])}", pct(x["mfe"]["median"]), pct(x["mae"]["median"]), "/".join(pct(x["forward_from_close"][str(h)]["median"]) for h in (5, 10, 20, 40))] for reason, x in data["simple_exit_attribution"]["summary"][policy].items()]))
        c = data["winner_concentration"][f"pooled_{policy}"]
        add("Winner profit concentration Top1/3/5/10 = " + "/".join(pct(c["top"][str(k)]["share_of_gross_profit"]) for k in (1, 3, 5, 10)) + f"；移除每 symbol 最大 winner 後 pooled net=${n(c['remove_each_symbol_largest_winner_net_pnl'])}；trim top1%/5% winner 後=${n(c['trim_top_1pct_winners_net_pnl'])}/${n(c['trim_top_5pct_winners_net_pnl'])}。")

    add("## 11. Tail risk：Worst trades 與 drawdowns")
    for policy in POLICIES:
        add(f"### {P[policy]} worst 10 trades")
        add(md(["Symbol/Position", "Entry", "Exit", "Reason", "Simple PnL", "MFE", "MAE", "Advanced same-entry PnL", "Loss avoided"], [[
            f"{r['symbol']}/{r['position_id']}", r["entry_date"][:10], r["final_exit_date"][:10], r["exit_final_close_reason"], f"${n(r['net_pnl'])}", pct(r["maximum_favorable_excursion"]), pct(r["maximum_adverse_excursion"]), f"${n(r['advanced_same_entry_net_pnl'])}", f"${n(r['advanced_loss_avoided'])}"
        ] for r in data["tail_risk"]["worst_trades"][policy]]))
        add(f"### {P[policy]} worst 10 drawdown episodes")
        add(md(["Symbol", "Start", "Trough", "Recovery", "Simple DD", "Advanced same-calendar", "Advanced loss avoided pp"], [[r["symbol"], r["start"], r["trough"], r["recovery"] or "未恢復", pct(r["depth"]), pct(r["advanced_same_calendar_return"]), n(r["advanced_loss_avoided_pp"])] for r in data["tail_risk"]["worst_drawdown_episodes"][policy]]))
    add("Advanced same-entry 是固定 Simple entry price/Q0 的獨立 lifecycle；drawdown comparison 則是兩個自然 portfolio 在同 calendar window 的 equity change。兩者不能混稱可投資 portfolio attribution。")

    add("## 12. Cost robustness")
    add(md(["Scenario", "Comparator", "Policy", "Return +/11", "Median ΔReturn pp", "Median ΔMDD pp", "Median ΔSharpe"], [[scenario, comparator, P[policy], x["return_improved"], n(x["return_delta_pp"]["median"]), n(x["mdd_delta_pp"]["median"]), n(x["sharpe_delta"]["median"])] for scenario, result in costs.items() for comparator in ("ADVANCED_V2", "BUY_AND_HOLD") for policy, x in result["breadth"][comparator].items()]))
    add("這是四個 deterministic cost scenarios，不是 optimization；Buy & Hold 同樣套用相同倍數的 buy/sell costs。Execution price 已含 slippage，commission 獨立扣除，沒有 double count。")

    add("## 13. Statistical uncertainty")
    add(md(["Comparator", "Policy", "N symbol-fold", "Mean ΔReturn pp", "Mean CI95", "Median ΔReturn pp", "Median CI95"], [[c, P[p], x["n"], n(x["point"]["mean"]), f"[{n(x['mean_ci95'][0])}, {n(x['mean_ci95'][1])}]", n(x["point"]["median"]), f"[{n(x['median_ci95'][0])}, {n(x['median_ci95'][1])}]"] for c, values in data["statistical_uncertainty"].items() for p, x in values.items()]))
    add("每個 policy 分開；唯一的 11 symbols × 6 chronological test blocks 以 ticker 與半年 block 兩向 cluster resampling 4000 次。Expanding/Rolling 重複 test 不重複計數。Interval 是小 cluster 樣本的描述性不確定性，不是假精確 p-value。")
    matched_boot = ambiguity["ambiguity_free_matched"]["two_way_cluster_bootstrap"]
    add(f"另對 ambiguity-free、policy-invariant、同 entry/P0/Q0 的 Simple−Advanced {matched_boot['n']} lifecycles 做 ticker×entry-half-year bootstrap：entry-cost-normalized mean 95% interval [{n(matched_boot['mean_ci95'][0])}, {n(matched_boot['mean_ci95'][1])}]pp。Buy & Hold 只有 window 首日單一 entry，沒有可誠實配對到每筆 Simple entry 的 position-level sample，因此採同 symbol×同 test block 配對，不虛構 matched trades。")

    add("## 14. Evidence gate")
    add(md(["Level", "Check", "Result"], [[level, key, "PASS" if value else "FAIL"] for level, checks in (("PROMISING", decision["promising_checks"]), ("STRONG", decision["strong_checks"])) for key, value in checks.items()]))
    add("Grade 只允許 NOT SUPPORTED／PROMISING — NEEDS FORWARD DATA／STRONG RETROSPECTIVE EVIDENCE — FREEZE FOR FORWARD TEST。所有 cutoff 已在 `research/viability_design.py` 先固定，report renderer 不會改 gate。")

    add("## 15. Caveats")
    add("11-symbol universe 是事後已知大型科技與 SPY/QQQ，存在 selection/survivorship 限制；研究期以科技多頭為主。Daily OHLC policy 都不是 tick path。重疊 signals、matched anchors、獨立 $100k sleeves 不能相加成一個可交易 portfolio。Yahoo adjustment contract 包含 adjusted-close basis，但 dividend cash flow 沒有另行入帳。短 fold Sharpe/CAGR 不穩定。Retrospective walk-forward 仍位於已知歷史資料，不是 unseen data。")
    add("## 16. Reproducibility / immutability")
    im = data["immutability"]
    add(f"Canonical database+audits hash `{im['before']['database_and_audits']}`；production source `{im['before']['production_source']}`；NVDA parquet `{im['before']['parquet']}`。Before/after 完全一致。Production execution/PnL/equity/history/audit differences 均為 0。研究 source hashes、每個 execution/equity/position hash、完整 request、data coverage 在 JSON。")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    body = json.loads((ROOT / "data/simple-v2-strategy-viability.json").read_text(encoding="utf-8"))
    print(render(body), end="")
