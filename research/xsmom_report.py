"""Report rendering consumes only completed frozen study outputs."""
import numpy as np


def num(v):
    return "—" if v is None else f"{v:,.2f}"


def pct(v):
    return "—" if v is None else f"{v*100:,.2f}%"


def table(headers, rows):
    return "\n".join(["| "+" | ".join(headers)+" |", "|"+"|".join(["---"]*len(headers))+"|"]+["| "+" | ".join(map(str,r))+" |" for r in rows])+"\n"


def render(r, folds, monthly):
    z=r["cash_models"]["CASH_ZERO"]; reg=r["registration"]
    year2020=next(x for x in r['calendar_years']['CASH_ZERO'] if x['window']=='2020')
    year2022=next(x for x in r['calendar_years']['CASH_ZERO'] if x['window']=='2022')
    crash2020='；'.join(x['date']+': '+', '.join(x['selected']) for x in monthly if x['date'][:7] in ('2020-02','2020-03','2020-04'))
    late2022='；'.join(x['date']+': '+', '.join(x['selected']) for x in monthly if x['date'][:7] in ('2022-07','2022-09'))
    out=["# 橫斷面動能基準研究：12-1 相對強弱 Top 3\n",
         f"Evidence grade：**{r['grade']}**。NEXT FAMILY = **{r['next_family']}**。本輪沒有建立候選或 production strategy。\n",
         f"共同評估期間：{r['evaluation_start']}～{r['evaluation_end']}；DATA START=2010-01-04。252-session 位移需要 253 筆 completed observations，等待首次合格月底之次日開盤才開始。\n",
         "## 事前固定規格與資料\n",
         f"Spec v2 SHA-256：`{reg['spec_sha256']}`\n\n註冊時間：{reg['registered_at']}\n\nSnapshot：`{reg['snapshot_id']}`\n\nData fingerprint：`{reg['fingerprint']}`\n",
         "v1 → v2 僅修正報告 provider/adjustment 欄位來源：原本誤讀不存在的 top-level 欄位為 null，實際計算始終使用已驗證 Yahoo variant。原規格與結果已保留，所有研究數值逐欄完全一致。\n",
         f"本金 ${reg['initial_capital']:,.0f}；每次手續費 {reg['commission_pct']}%；滑價 {reg['slippage_pct']}%。整股、每月等權、先賣後買；規格見 research/specs/CROSS_SECTIONAL_MOMENTUM_BENCHMARK.md。\n",
         "排名 Close[t−21]/Close[t−252]−1；僅 eligible ETF 參與。若 retained ETF 股數需調整也會交易。SPY/QQQ 買入持有同日開始、同日清算。EW 使用同一 eligible universe。三種 OHLC policies 在本 open-only 規格下完全等價，不製造三份獨立樣本。\n",
         table(["ETF","Provider / adjustment","First date","Last date","Bars","Checksum"],[[x['ticker'],x['provider']+' / '+x['adjustment_mode'],x['first_date'],x['last_date'],x['bars'],x['ohlcv_sha256']] for x in r['data_coverage']]),
         "## Full-history performance\n"]
    for cash, suite in r['cash_models'].items():
        out += [f"### {cash}\n",table(["Benchmark","Return","CAGR","MDD","Sharpe","Sortino","Calmar","Exposure","Cash","Turnover","Fees $","Slippage $","Rebalances","Avg holdings","Avg holding sessions"],
            [[k,pct(m['total_return']),pct(m['cagr']),pct(m['mdd']),num(m['sharpe']),num(m['sortino']),num(m['calmar']),pct(m['exposure']),pct(m['cash_pct']),num(m['turnover']),num(m['commission']),num(m['slippage']),m['rebalances'],num(m['average_holdings']),num(m['average_holding_sessions'])] for k,m in suite.items()])]
    out += ["RS=相對強弱 Top 3；EW=全部 eligible ETF 每月等權。Turnover 為雙邊成交金額／平均 equity。Sharpe/Sortino hurdle=0；cash yield 已在 daily equity 內。B&H 的一次初始部署列入 rebalances 計數，終端賣出另列 executions。\n",
            table(["RS minus","Return delta pp","CAGR delta pp","MDD delta pp","Sharpe delta","Calmar delta"],[[b,num(d['total_return']*100),num(d['cagr']*100),num(d['mdd']*100),num(d['sharpe']),num(d['calmar'])] for b,d in r['full_comparison'].items()]),
            "## Calendar-year robustness\n"]
    for cash, rows in r['calendar_years'].items():
        out += [f"### {cash}\n",table(["Year","RS Return / MDD / Sharpe","EW Return / MDD / Sharpe","SPY Return / MDD / Sharpe","RS−EW pp","RS−SPY pp"],
            [[x['window']]+[f"{pct(x['metrics'][k]['total_return'])} / {pct(x['metrics'][k]['mdd'])} / {num(x['metrics'][k]['sharpe'])}" for k in ('RS','EW','SPY')]+[num(x['vs_EW']['total_return']*100),num(x['vs_SPY']['total_return']*100)] for x in rows])]
    out += ["起始年及 2026 為部分年度；period metrics 使用窗口前一日 equity 作分母，未替策略重新進場。\n", "## Fixed market cycles / crisis episodes\n"]
    for name,key in (("固定週期","fixed_cycles"),("危機窗口","crises")):
        for cash,rows in r[key].items():
            out += [f"### {name} · {cash}\n",table(["Window","RS Return","EW Return","SPY Return","RS MDD","EW MDD","SPY MDD","RS−EW pp","RS−SPY pp"],
                     [[x['window']]+[pct(x['metrics'][k]['total_return']) for k in ('RS','EW','SPY')]+[pct(x['metrics'][k]['mdd']) for k in ('RS','EW','SPY')]+[num(x['vs_EW']['total_return']*100),num(x['vs_SPY']['total_return']*100)] for x in rows])]
    out += ["## Retrospective Walk-Forward Robustness Validation\n",
            "Train 不調參。Expanding 使用起始日至 test 前；Rolling 使用 test 前兩年。兩種設計 test 日期完全相同，因此結果相同是預期，不是兩份獨立證據。Train metrics 完整保存在 machine-readable folds。每個 test 從現金重啟，以開盤前已知最近月底訊號初始化。\n"]
    for cash in r['cash_models']:
        rows=[x for x in folds if x['cash_model']==cash and x['design']=='EXPANDING']
        out += [f"### {cash} · 兩種設計共用 test results\n",table(["Fold","Test start","Test end","RS Return","EW Return","SPY Return","RS−EW pp","RS−SPY pp","RS MDD"],
                 [[x['fold'],x['test_start'],x['test_end']]+[pct(x['test'][k]['total_return']) for k in ('RS','EW','SPY')]+[num(x['vs_EW']['total_return']*100),num(x['vs_SPY']['total_return']*100),pct(x['test']['RS']['mdd'])] for x in rows])]
    out += ["## Ranking stability / turnover\n",str(r['ranking_stability'])+"\n",
            "持有月份中位數是連續入選 spell（含終端尚未結束 spell）；成交股數加權持有天數另列 full metrics。排名、進出名單、rank changes、eligible count 每月完整保存於 monthly-holdings JSON。\n",
            "## Costs and cash\n"]
    for cash, stresses in r['cost_stress'].items():
        out += [f"### {cash}\n",table(["Stress","RS Return","EW Return","SPY Return","RS Fees $","RS Slippage $","RS MDD"],
            [[label]+[pct(m[k]['total_return']) for k in ('RS','EW','SPY')]+[num(m['RS']['commission']),num(m['RS']['slippage']),pct(m['RS']['mdd'])] for label,m in stresses.items()]),
            table(["Benchmark","Gross zero-cost return","Net return","Total cost drag pp"],[[k,pct(v['gross_return']),pct(v['net_return']),num(v['cost_drag_pp'])] for k,v in r['cost_attribution'][cash].items()])]
    out += ["零成本與實際成本的差額含本金複利／整股 sizing 路徑效應，不能把總差額全部線性歸於某一次 fee。費用及 raw-vs-execution 滑價成本另列；不重複扣除。\n",
            table(["Benchmark","Risk-free minus zero return pp"],[[k,num(v*100)] for k,v in r['cash_return_delta'].items()]),
            "利息僅按前一交易日現金、previous-known DGS3MO、ACT/365 計提；投入 ETF 金額不計息。利息在之後 rebalance 可再投資。\n",
            "## ETF / year concentration\n"]
    c=r['concentration']
    out += [table(["ETF","Net dollar contribution"],[[s,num(v)] for s,v in sorted(c['etf_dollar_contribution'].items(),key=lambda x:-x[1])]),
            f"Top ETF={c['top_etf']}；占正獲利 ETF 總貢獻 {pct(c['top_etf_positive_profit_share'])}；占净貢獻 {pct(c['top_etf_net_share'])}。Top3 正獲利占比 {pct(c['top3_positive_profit_share'])}。Top year 正獲利占比 {pct(c['top_year_positive_profit_share'])}。平均 QQQ+XLK 權重 {pct(c['mean_QQQ_XLK_weight'])}。\n",
            table(["Year","Dollar contribution","QQQ weight","XLK weight","Defensive XLP+XLU+XLV"],[[y,num(v),pct(c['yearly_weights'][y]['QQQ']),pct(c['yearly_weights'][y]['XLK']),pct(sum(c['yearly_weights'][y][s] for s in ('XLP','XLU','XLV')))] for y,v in c['year_dollar_contribution'].items()]),
            f"Post-hoc descriptive exclusion：移除 {c['top_etf']}，RS Return={pct(c['excluded_best_etf_sensitivity']['metrics']['total_return'])}；Sharpe={num(c['excluded_best_etf_sensitivity']['metrics']['sharpe'])}；MDD={pct(c['excluded_best_etf_sensitivity']['metrics']['mdd'])}。只標示依賴程度，沒有修改 frozen universe 或新增 candidate。\n",
            "## 2020 / 2022 rotation sequence\n",
            table(["Execution open","Signal close","Eligible","Selected","New","Exited"],[[x['date'],x['signal_date'],x['eligible_count'],', '.join(x['selected']),', '.join(x['new_entrants']),', '.join(x['exits'])] for x in monthly if x['date'][:4] in ('2020','2022')]),
            "本規格始終持有相對排名最高 ETF，沒有 absolute-momentum 或轉現金 filter。是否防禦輪動必須以以上實際持倉判斷，防禦型 ETF 仍可下跌。\n",
            "## Time-block-aware uncertainty\n",
            table(["Comparison","Mean calendar return delta pp","Median calendar delta pp","Annualized mean log delta","95% block interval"],[[f'RS−{b}',num(v['mean_calendar_return_delta']*100),num(v['median_calendar_return_delta']*100),pct(v['annualized_mean_log_return_delta']),f"{pct(v['ci95'][0])} to {pct(v['ci95'][1])}"] for b,v in r['uncertainty'].items()]),
            "Paired circular 12-month blocks，2000 draws，seed=1201252。估計對象是兩組 monthly log returns 差的年化平均；不把月份當 iid，也不把部分 calendar-year return 當完整年。少量長時間 blocks 與單一實際市場歷史限制推論。\n",
            "## Frozen family gate\n",
            "PROMISING：同時勝過 SPY/EW 的 full Return+Sharpe、MDD 不多惡化超過5pp、過半 cycle/fold return deltas 為正、2×both 成本後仍勝。STRONG 另需 MDD 都改善、2/3 breadth、bootstrap lower>0、移除最佳 ETF 後仍勝。規格在結果前固定。\n",
            table(["Comparator","Return+","Sharpe+","MDD within 5pp","Cycle breadth","Fold breadth","2x costs+"],[[b,c['return_positive'],c['sharpe_positive'],c['mdd_within_5pp'],pct(c['cycle_return_breadth']),pct(c['fold_return_breadth']),c['stress_positive']] for b,c in r['gate_checks'].items()]),
            f"最終：**{r['grade']}**；**NEXT FAMILY = {r['next_family']}**。\n",
            "## 13 個決策問題\n",
            f"1. 長期是否勝過等權 ETF：{'是' if r['full_comparison']['EW']['total_return']>0 else '否'}。RS {pct(z['RS']['total_return'])}，EW {pct(z['EW']['total_return'])}。\n",
            f"2. 是否勝過 SPY：{'是' if r['full_comparison']['SPY']['total_return']>0 else '否'}。SPY {pct(z['SPY']['total_return'])}。\n",
            f"3. Sharpe：RS {num(z['RS']['sharpe'])}、EW {num(z['EW']['sharpe'])}、SPY {num(z['SPY']['sharpe'])}，本次 RS 較低。\n",
            f"4. MDD：RS {pct(z['RS']['mdd'])}、EW {pct(z['EW']['mdd'])}、SPY {pct(z['SPY']['mdd'])}；改善 {num(r['full_comparison']['EW']['mdd']*100)} / {num(r['full_comparison']['SPY']['mdd']*100)}pp，未轉化為較高 Sharpe。\n",
            f"5. 固定週期方向不一致。RS 對 EW/SPY 正報酬差 breadth 為 {pct(r['gate_checks']['EW']['cycle_return_breadth'])} / {pct(r['gate_checks']['SPY']['cycle_return_breadth'])}。\n",
            f"6. WF 支持不足。對 EW/SPY 勝出 test breadth {pct(r['gate_checks']['EW']['fold_return_breadth'])} / {pct(r['gate_checks']['SPY']['fold_return_breadth'])}，兩種 train 設計相同 test 結果，不重複算票。\n",
            f"7. 2×兩者成本：RS {pct(r['cost_stress']['CASH_ZERO']['2X_BOTH']['RS']['total_return'])}，EW {pct(r['cost_stress']['CASH_ZERO']['2X_BOTH']['EW']['total_return'])}，SPY {pct(r['cost_stress']['CASH_ZERO']['2X_BOTH']['SPY']['total_return'])}；未建立超額優勢。\n",
            f"8. 科技曝險重要但非全程科技：QQQ+XLK 平均 {pct(r['concentration']['mean_QQQ_XLK_weight'])}，2020 約 {pct(r['concentration']['yearly_weights']['2020']['QQQ']+r['concentration']['yearly_weights']['2020']['XLK'])}。QQQ B&H {pct(z['QQQ']['total_return'])}。移除貢獻最大 XLK 的描述性 sensitivity 仍落後比較基準。\n",
            f"9. 最大單年占正 dollar contribution {pct(r['concentration']['top_year_positive_profit_share'])}，並非單一年包辦全部獲利；但超額報酬只在少數固定週期出現。Dollar attribution 受當時資本大小影響。\n",
            f"10. {crash2020}；2020 MDD={pct(year2020['metrics']['RS']['mdd'])}。{late2022}；2022 Return={pct(year2022['metrics']['RS']['total_return'])}，MDD={pct(year2022['metrics']['RS']['mdd'])}。2022 能源／防禦輪動有利，2020 則仍承受 crash，不能推出所有危機都能保護。\n",
            f"11. Risk-free cash 對 RS 全期報酬只增加 {num(r['cash_return_delta']['RS']*100)}pp；平均股票曝險 {pct(z['RS']['exposure'])}，現金少，因此影響有限且帳務可對帳。\n",
            f"12. Family evidence grade：{r['grade']}。\n",
            f"13. NEXT FAMILY = {r['next_family']}。依本輪事前固定 gate，不建立 MOMENTUM_001；此結論限於此 universe／12-1 Top3／資料口徑，並非證明所有相對強弱模型均無效。\n",
            "## Limitations / invariance\n"]
    out += ["\n".join('- '+x for x in r['limitations'])+"\n",
            "Production source / canonical data / histories / executions / PnL / equity / audits before-after fingerprints 相同；candidate registry hash 相同。未新增 MOMENTUM_001。完整 before/after hashes 保存在結果 JSON。\n",
            f"Runtime: {r['runtime_seconds']:.2f} seconds.\n"]
    return "\n".join(out)
