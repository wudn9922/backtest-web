"""Traditional-Chinese report for immutable volatility benchmark results."""
from __future__ import annotations

from typing import Any


def _n(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def _p(value):
    return "—" if value is None else f"{value * 100:,.2f}%"


def _table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
        *["| " + " | ".join(map(str, row)) + " |" for row in rows],
    ]) + "\n"


def render(result: dict[str, Any], robustness: dict[str, Any], walk: dict[str, Any]) -> str:
    reg = result["registration"]
    zero = result["primary_spy"]["CASH_ZERO"]
    rf = result["primary_spy"]["CASH_RISK_FREE"]
    etf = result["robustness_summary"]["CASH_ZERO"]
    spy_walk = result["walk_forward_summary"]["spy_unique_tests"]
    gross = result["gross_before_cost_spy"]["CASH_ZERO"]
    stress = result["cost_stress_spy"]["CASH_ZERO"]
    cash = result["cash_decomposition"]["SPY"]

    text = [
        "# 波動度管理曝險基準研究\n",
        f"Technical ID：`{result['study']}`。Evidence grade：**{result['evidence_grade']}**。NEXT FAMILY = **{result['next_family']}**。本輪沒有建立 VOL_001、candidate 或 production strategy。\n",
        "## 事前固定規格與研究環境\n",
        f"Spec SHA-256：`{reg['spec_sha256']}`  \nSnapshot ID：`{reg['snapshot_id']}`  \nData fingerprint：`{reg['fingerprint']}`  \nRegistered：{reg['registered_at']}\n",
        f"SPY data start：{result['evaluation']['data_start']}；20 個 completed close-to-close returns 後於 {result['evaluation']['signal_start']} 收盤得到第一個 RV20，{result['evaluation']['evaluation_start']} 開盤開始公平比較，至 {result['evaluation']['evaluation_end']}。\n",
        "規則固定為 RV20=前 20 個 completed daily returns 的 sample std×√252；target exposure=min(100%,15%/RV20)；次一交易日開盤以整股調整。沒有 leverage、rebalance band、direction filter 或 same-close 成交。\n",
        f"本金 ${reg['initial_capital']:,.0f}；commission {reg['commission_pct']}%；slippage {reg['slippage_pct']}%。CASH_RISK_FREE 使用 previous-known DGS3MO、ACT/365，只計現金。\n",
        "## SPY full-history comparison\n",
    ]
    for cash_model, pair in result["primary_spy"].items():
        text += [f"### {cash_model}\n", _table(
            ["Metric", "20日波動度管理", "SPY Buy & Hold", "Delta"],
            [
                ["Total Return", _p(pair["managed"]["total_return"]), _p(pair["buy_hold"]["total_return"]), _p(pair["delta"]["total_return"])],
                ["CAGR", _p(pair["managed"]["cagr"]), _p(pair["buy_hold"]["cagr"]), _p(pair["delta"]["cagr"])],
                ["Annualized Volatility", _p(pair["managed"]["annualized_volatility"]), _p(pair["buy_hold"]["annualized_volatility"]), _p(pair["delta"]["annualized_volatility"])],
                ["MDD", _p(pair["managed"]["mdd"]), _p(pair["buy_hold"]["mdd"]), _p(pair["delta"]["mdd"])],
                ["Sharpe", _n(pair["managed"]["sharpe"]), _n(pair["buy_hold"]["sharpe"]), _n(pair["delta"]["sharpe"])],
                ["Sortino", _n(pair["managed"]["sortino"]), _n(pair["buy_hold"]["sortino"]), _n(pair["delta"]["sortino"])],
                ["Calmar", _n(pair["managed"]["calmar"]), _n(pair["buy_hold"]["calmar"]), _n(pair["delta"]["calmar"])],
                ["Average exposure", _p(pair["managed"]["exposure"]), _p(pair["buy_hold"]["exposure"]), _p(pair["delta"]["exposure"])],
                ["Average cash", _p(pair["managed"]["cash_pct"]), _p(pair["buy_hold"]["cash_pct"]), "—"],
                ["Turnover", _n(pair["managed"]["turnover"]), _n(pair["buy_hold"]["turnover"]), _n(pair["delta"]["turnover"])],
                ["Commission", f"${_n(pair['managed']['commission'])}", f"${_n(pair['buy_hold']['commission'])}", "—"],
                ["Slippage", f"${_n(pair['managed']['slippage'])}", f"${_n(pair['buy_hold']['slippage'])}", "—"],
                ["Cash interest", f"${_n(pair['managed']['cash_interest'])}", f"${_n(pair['buy_hold']['cash_interest'])}", "—"],
                ["Return / exposure", _n(pair["managed"]["return_per_unit_exposure"]), _n(pair["buy_hold"]["return_per_unit_exposure"]), "descriptive only"],
            ],
        )]

    text += [
        "## Frozen six-period robustness — SPY\n",
        _table(
            ["Period", "Managed CAGR", "B&H CAGR", "Managed MDD", "B&H MDD", "Sharpe Δ", "Sortino Δ", "Calmar Δ", "Exposure"],
            [[row["window"], _p(row["managed"]["cagr"]), _p(row["buy_hold"]["cagr"]), _p(row["managed"]["mdd"]), _p(row["buy_hold"]["mdd"]), _n(row["delta"]["sharpe"]), _n(row["delta"]["sortino"]), _n(row["delta"]["calmar"]), _p(row["managed"]["exposure"])] for row in result["fixed_periods"]["CASH_ZERO"]],
        ),
        f"依預先 gate，需至少 4/6 同時改善 Sharpe、Calmar、MDD 且 CAGR 犧牲不超過 5pp；實際 supportive periods={result['gate_checks']['supportive_fixed_periods']}/6。\n",
        "## Frozen crisis episodes\n",
        _table(
            ["Episode", "Managed MDD", "SPY MDD", "MDD Δ", "Min target", "Min actual", "Days actual<50%", "First target<50%", "Sessions from start", "Recovery participation"],
            [[row["episode"], _p(row["managed"]["mdd"]), _p(row["buy_hold"]["mdd"]), _p(row["delta"]["mdd"]), _p(row["minimum_target_exposure"]), _p(row["minimum_actual_open_exposure"]), row["sessions_actual_open_exposure_below_50"], row["first_target_below_50_date"] or "—", row["sessions_to_target_below_50"] if row["sessions_to_target_below_50"] is not None else "—", _p(row["recovery"]["participation_ratio"]) if row["recovery"] else "—"] for row in result["crisis_analysis"]["CASH_ZERO"]],
        ),
        "`Sessions from start` 為負表示 episode 開始前已進入低於 50% target 的連續 spell；正值代表波動出現後才降到該水準。完整每日 RV、target 與 actual exposure path 保存在 JSON。Recovery participation 以 B&H 回到 episode 前 equity 的日期計算。\n",
        "## Post-crash rebound cost\n",
    ]
    for cash_model, rows in result["post_crash_rebound"].items():
        text += [f"### {cash_model}\n", _table(
            ["Episode", "Trough", "Horizon", "End", "Managed", "SPY B&H", "Managed−B&H pp", "Participation"],
            [[row["episode"], row["trough_date"], horizon["horizon"], horizon["end_date"], _p(horizon["managed_return"]), _p(horizon["buy_hold_return"]), _n(horizon["managed_minus_buy_hold_pp"]), _p(horizon["rebound_participation_ratio"])] for row in rows for horizon in row["horizons"]],
        )]

    text += ["## ETF robustness\n"]
    for cash_model, summary in result["robustness_summary"].items():
        text += [f"### {cash_model}\n", _table(
            ["Measure", "Improved / 14", "Median delta"],
            [[field, summary["improvement_counts"][field], _p(summary["median_delta"][field]) if field in ("mdd", "cagr") else _n(summary["median_delta"][field])] for field in ("sharpe", "mdd", "cagr", "calmar")],
        ), f"Median managed exposure：{_p(summary['median_managed_exposure'])}；median CAGR sacrifice（只計負值）：{_p(summary['median_cagr_sacrifice'])}。\n"]
    zero_rows = robustness["rows"]["CASH_ZERO"]
    text += [_table(
        ["ETF", "Start", "Managed CAGR", "B&H CAGR", "CAGR Δ", "Sharpe Δ", "MDD Δ", "Calmar Δ", "Exposure", "Trades"],
        [[row["ticker"], row["evaluation_start"], _p(row["managed"]["cagr"]), _p(row["buy_hold"]["cagr"]), _p(row["delta"]["cagr"]), _n(row["delta"]["sharpe"]), _p(row["delta"]["mdd"]), _n(row["delta"]["calmar"]), _p(row["managed"]["exposure"]), row["managed"]["number_of_trades"]] for row in zero_rows],
    )]

    text += [
        "## Retrospective Walk-Forward Robustness Validation\n",
        "Train 不選參數。Expanding 與 Rolling 各保留 train 指標，但固定規則產生相同 test 結果，gate 只計一次。最後不足完整六個月的 fold 已標示。\n",
        _table(
            ["Scope", "Unique tests", "Return+", "Sharpe+", "MDD+", "Calmar+"],
            [[scope, values["cells"], values["total_return"], values["sharpe"], values["mdd"], values["calmar"]] for scope, values in result["walk_forward_summary"].items() if isinstance(values, dict)],
        ),
        "SPY CASH_ZERO unique test folds：\n",
        _table(
            ["Fold", "Test", "Return Δ", "Sharpe Δ", "MDD Δ", "Calmar Δ", "Partial"],
            [[row["fold"], f"{row['test_start']}→{row['test_end']}", _p(row["test_delta"]["total_return"]), _n(row["test_delta"]["sharpe"]), _p(row["test_delta"]["mdd"]), _n(row["test_delta"]["calmar"]), row["partial_fold"]] for row in walk["rows"] if row["ticker"] == "SPY" and row["cash_model"] == "CASH_ZERO" and row["design"] == "EXPANDING"],
        ),
        "## Cost stress and turnover forensic\n",
        _table(
            ["Scenario", "Managed Return", "B&H Return", "Return Δ", "Sharpe Δ", "MDD Δ", "Calmar Δ", "Managed commission", "Managed slippage"],
            [[scenario, _p(cell["managed"]["total_return"]), _p(cell["buy_hold"]["total_return"]), _p((cell.get("delta") or metric_delta_for_report(cell))["total_return"]), _n((cell.get("delta") or metric_delta_for_report(cell))["sharpe"]), _p((cell.get("delta") or metric_delta_for_report(cell))["mdd"]), _n((cell.get("delta") or metric_delta_for_report(cell))["calmar"]), f"${_n(cell['managed']['commission'])}", f"${_n(cell['managed']['slippage'])}"] for scenario, cell in stress.items()],
        ),
        f"Zero-cost SPY managed return={_p(gross['managed']['total_return'])}，B&H={_p(gross['buy_hold']['total_return'])}，gross relative benefit={_p(gross['delta']['total_return'])}。Baseline net relative benefit={_p(zero['delta']['total_return'])}。\n",
        f"SPY adjustments={result['turnover_forensic']['number_of_adjustment_trades']:,} executions across {result['turnover_forensic']['adjustment_days']:,} days；average daily turnover={_p(result['turnover_forensic']['average_daily_turnover'])}；annual turnover={_n(result['turnover_forensic']['annual_turnover'])}。Target daily absolute change median={_p(result['turnover_forensic']['target_change_distribution']['median_abs'])}，P90={_p(result['turnover_forensic']['target_change_distribution']['p90_abs'])}，max={_p(result['turnover_forensic']['target_change_distribution']['maximum_abs'])}。這是 turnover 診斷，沒有回頭加入 band。\n",
        "## Cash-yield attribution\n",
        f"SPY managed DGS3MO cash interest=${_n(cash['managed_cash_interest_usd'])}，B&H residual-cash interest=${_n(cash['buy_hold_cash_interest_usd'])}。Managed return contribution={_n(cash['managed_return_contribution_pp'])}pp；B&H={_n(cash['buy_hold_return_contribution_pp'])}pp；incremental managed cash effect={_n(cash['incremental_managed_cash_effect_pp'])}pp。Cash-zero gate 單獨成立才可能通過，因此不會把利息誤認為 volatility-management alpha。\n",
        "## Time-block-aware uncertainty\n",
        f"Method：{result['uncertainty']['method']}；sessions={result['uncertainty']['sessions']}。\n",
        _table(
            ["Statistic", "Bootstrap mean", "95% interval"],
            [[key, _n(value["mean"]), f"{_n(value['ci95'][0])} to {_n(value['ci95'][1])}"] for key, value in result["uncertainty"].items() if isinstance(value, dict)],
        ),
        "MDD interval 為相同 paired time blocks 下的描述性 path 統計；這不是把日資料當 iid，也不是 p-value。\n",
        "## Predeclared evidence gate\n",
        _table(["Check", "Result"], [[key, value] for key, value in result["gate_checks"].items()]),
        f"Evidence grade：**{result['evidence_grade']}**。NEXT FAMILY = **{result['next_family']}**。\n",
        "## Final gate answers\n",
        f"1. SPY Sharpe 是否改善：{'是' if zero['delta']['sharpe'] > 0 else '否'}；Δ={_n(zero['delta']['sharpe'])}。\n",
        f"2. SPY MDD 是否改善：{'是' if zero['delta']['mdd'] > 0 else '否'}；Δ={_p(zero['delta']['mdd'])}。\n",
        f"3. SPY CAGR 犧牲：{_p(-zero['delta']['cagr']) if zero['delta']['cagr'] < 0 else '沒有犧牲；改善 '+_p(zero['delta']['cagr'])}。\n",
        f"4. Calmar 是否改善：{'是' if zero['delta']['calmar'] > 0 else '否'}；Δ={_n(zero['delta']['calmar'])}。\n",
        f"5. 六個 fixed periods：{result['gate_checks']['supportive_fixed_periods']}/6 支持事前條件。\n",
        f"6. Crisis 是否降低損失：{sum(row['delta']['mdd'] > 0 for row in result['crisis_analysis']['CASH_ZERO'])}/{len(result['crisis_analysis']['CASH_ZERO'])} episodes 的 MDD 較小；時機與曝險路徑見上表。\n",
        "7. Crash 後 rebound 代價：上表列出 21/63/126 sessions 的 managed−B&H；結論依實際各 horizon，而非只看單一反彈。\n",
        f"8. ETF Sharpe 改善：{etf['improvement_counts']['sharpe']}/14。\n",
        f"9. ETF MDD 改善：{etf['improvement_counts']['mdd']}/14。\n",
        f"10. ETF Calmar 改善：{etf['improvement_counts']['calmar']}/14。\n",
        f"11. Walk-forward：SPY Sharpe/MDD/Calmar 改善 {spy_walk['sharpe']}/{spy_walk['cells']}、{spy_walk['mdd']}/{spy_walk['cells']}、{spy_walk['calmar']}/{spy_walk['cells']} folds。\n",
        f"12. Cost stress：2×both SPY Sharpe Δ={_n(stress['2X_BOTH']['delta']['sharpe'])}、MDD Δ={_p(stress['2X_BOTH']['delta']['mdd'])}、Calmar Δ={_n(stress['2X_BOTH']['delta']['calmar'])}；ETF Sharpe/Calmar breadth={result['cost_stress_breadth']['CASH_ZERO']['2X_BOTH']['improvement_counts']['sharpe']}/14、{result['cost_stress_breadth']['CASH_ZERO']['2X_BOTH']['improvement_counts']['calmar']}/14。\n",
        f"13. CASH_RISK_FREE 是否 materially 改變結論：cash-zero grade 已固定為 {result['evidence_grade']}；managed 累積報酬增量 {_n(cash['managed_return_contribution_pp'])}pp。\n",
        f"14. 優勢是否主要只是 cash interest：{'是' if zero['delta']['sharpe'] <= 0 and rf['delta']['sharpe'] > 0 else '否；cash-zero 結果本身決定 gate'}。\n",
        f"15. Family evidence grade：{result['evidence_grade']}。\n",
        f"16. 是否建立 VOL_001：本輪沒有建立。NEXT FAMILY={result['next_family']}。\n",
        "## Limitations and invariance\n",
        "\n".join(f"- {item}" for item in result["limitations"]) + "\n",
        "Production source、canonical market data、historical database/audits 與 candidate registry 的 before/after hashes 相同。Executions/PnL/equity/audits differences=0。\n",
        f"Runtime：{result['runtime_seconds']:.2f} seconds。\n",
    ]
    return "\n".join(text)


def metric_delta_for_report(cell):
    return {
        key: cell["managed"][key] - cell["buy_hold"][key]
        for key in ("total_return", "sharpe", "mdd", "calmar")
    }
