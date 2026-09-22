"""Render the saved M3 retrospective walk-forward evidence."""
import json
from research import ROOT

P={'conservative':'保守','ohlc_heuristic':'OHLC 推估','favorable':'有利'}
def n(x,d=2):return '—' if x is None else f'{x:,.{d}f}'
def pct(x,d=2):return '—' if x is None else f'{100*x:,.{d}f}%'
def md(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+['| '+' | '.join(str(v).replace('|','／').replace('\n',' ') for v in r)+' |' for r in rows])

def render(d,folds):
    L=[]
    def add(s=''):L.extend([s,''])
    rows=[dict(zip(folds['columns'],r)) for r in folds['rows']]
    add('# M3 Retrospective Walk-Forward Robustness Validation')
    add('研究日期：2026-09-05。這是 **Retrospective Walk-Forward Robustness Validation**，不是 true out-of-sample、不是 unseen-data validation。M3 是用 2021-09-01～2026-09-01 發現，本報告的 test 區間也在該 discovery sample 內。沒有調參、candidate switching、production v3 或策略修改。')
    add('## 1. Executive conclusion 與 11 個問題')
    dec=d['decision']; mech=d['mechanism_summary']['conservative']; earlier=d['earlier_historical_external_check']
    add(f'最終分類：**{dec["classification"]}**。依事前 gate，不值得 freeze M3 進入真正 forward test，因此沒有建立 `reports/m3-frozen-spec.md`。Production Advanced v2 保持不變。')
    add(md(['問題','答案'],[
      ['1. Expanding test folds',f'以每 fold 的 11-symbol Return delta 中位數 > 0 定義，0/6 改善；但 train gate 6/6 PASS。'],
      ['2. Rolling 是否一致？','Raw test 完全相同（同一組 test 邊界）；rolling train gate 5/6 PASS，F2 因集中度與部分 policy median 失敗。Gate-conditioned stitched 改善比 expanding 小。'],
      ['3. Cross-symbol breadth',f'66 個唯一 symbol-fold cells：保守 {dec["policy_positive_symbol_fold_cells"]["conservative"]}/66、推估 {dec["policy_positive_symbol_fold_cells"]["ohlc_heuristic"]}/66、有利 {dec["policy_positive_symbol_fold_cells"]["favorable"]}/66 改善；每個 policy 的六個 fold median 均為 0。'],
      ['4. 三種 policy',f'Mean delta 都正（+{n(d["walk_forward"]["bootstrap"]["conservative"]["mean_delta_pp"])}／+{n(d["walk_forward"]["bootstrap"]["ohlc_heuristic"]["mean_delta_pp"])}／+{n(d["walk_forward"]["bootstrap"]["favorable"]["mean_delta_pp"])}pp），但 symbol×fold bootstrap 區間全部跨零，方向廣度不足。'],
      ['5. SPY/QQQ','沒有重現「ETF 一致較差」：SPY 3 positive/0 negative/3 tie folds；QQQ 3 positive/2 negative/1 tie。保守 stitched M3 相對 v2：SPY +8.96pp、QQQ +2.77pp，但 QQQ MDD 較差 1.73pp。'],
      ['6. BreakDayLow noise？',f'在保守模式 38 次中：FALSE {mech["classification"]["FALSE_BREAKDOWN"]}、TRUE {mech["classification"]["TRUE_BREAKDOWN"]}、MIXED {mech["classification"]["MIXED"]}；依固定描述標準 false 明顯較多，但仍有真跌破和重大尾損。'],
      ['7. 最大 tail risk',f'TSLA 2025-01-30 entry：M3−v2 −$10,232.99（−11.08pp entry cost），Break 後 MAE −28.81%，額外 marked drawdown −12.40pp。保守 5th-percentile loss −5.39pp。'],
      ['8. Earlier check',f'不支持也不反駁：快取只能提供 {earlier["actual_common_fully_warmed_period"][0]}～{earlier["actual_common_fully_warmed_period"][1]}、{earlier["bars"]} sessions；1/11 改善且 median 0，遠低於事前 3年/500 sessions 有效門檻。Yahoo HTTPS 無法連線，沒有繞過或混用資料。'],
      ['9. Leave-one-symbol-out','其他 10 symbols 的 full-sample gate 每次都通過，故不是 NVDA/META 單獨撐起；但 held-out 本身至少 2 policies 改善的只有 7/11，未達事前 8/11。NVDA=3、META=3、TSLA=1 policies。'],
      ['10. 最終分類',dec['classification']],
      ['11. Freeze forward test？','否。保留本輪固定研究定義與 failure criteria 作稽核，但不建立 M3_FROZEN_SPEC，也不進入真正 forward test。']]))
    add('## 2. Freeze、唯一變更與參數')
    add('唯一 structural change：BREAK_PROTECTION 中 `Low < BreakDayLow` 時不 full exit；BreakDayLow tracking、episode、`Low(t) > MA(t)` CLOSE reset 及 reset 後次日 normal MA risk re-arm 全保留。Entry Zone、Volume、Day2、MA(t-1) half-stop、50% current qty、First TP、Protective、Bias/ATR、20% Q0、gap/cost/slippage/policy 全不變。')
    add('參數直接複製 canonical Advanced request；程式只可覆寫 ticker、fold dates、intrabar policy。完整 request、source hash 與列舉語意在 JSON `freeze`；production M3 沒有註冊。')
    add(md(['Canonical','ID','Return','MDD','Sharpe','Positions'],[[k,v['backtest_id'],pct(v['summary']['total_return']),pct(v['summary']['max_drawdown']),n(v['summary']['sharpe_ratio']),v['summary']['number_of_positions']] for k,v in d['canonical'].items()]))
    add('## 3. 事前 fold 與 deployment gate')
    add('六個非重疊 test folds，每個約六個月，起於 2023-09-01；Expanding 從 2021-09-01 累積 train，Rolling 僅保留 test 前兩年。Train 不選參數，只計算截至當時可見 evidence。每個 train/test portfolio 都在 window 第一日空倉並以 canonical capital 重新開始；train position、capital、PnL 不流入 test。完整 predeclared wording 在 JSON `design`。')
    add(md(['Design','Fold','Train requested','Test requested','Gate','Policy passes'],[[design,f,f'{x["train_start"]}～{x["train_end"]}',f'{x["test_start"]}～{x["test_end"]}',g['composite']['status'],', '.join(P[p] for p in g['composite']['passed_policies']) or '無'] for design,fs in d['train_gates'].items() for f,g in fs.items() for x in [next(z for z in d['folds'] if z['design']==design and z['fold']==f)] ]))
    add('Policy gate：Return nonnegative strict majority ≥6/11、median Return delta >0、median MDD delta ≥−3pp、最大單一 positive symbol ≤正改善總和50%。Fold 只有 Conservative 及至少另一 policy 同時通過才 PASS。此文字與 cutoff 在計算 test 前已寫入 research source；結果不會回改 gate。')
    add('## 4. Test fold breadth')
    add(md(['Fold','Policy','Return +/11','Sharpe +/11','MDD +/11','Median ΔReturn pp','Median ΔSharpe','Median ΔMDD pp'],[[r['fold'],P[r['policy']],r['return_improved'],r['sharpe_improved'],r['mdd_improved'],n(r['median_return_delta_pp']),n(r['median_sharpe_delta']),n(r['median_mdd_delta_pp'])] for r in d['walk_forward']['fold_breadth']]))
    add('M3 的唯一差異在短 fold 中很少被觸發，因此 34/66、35/66、41/66 cells 分別在保守／推估／有利完全相同；median=0 是結構稀疏，不代表每筆 effect 為零。可是依 freeze gate，這仍不能算 cross-symbol 多數改善。')
    add('### Symbol × fold cluster/block uncertainty')
    add(md(['Policy','Positive/Negative/Zero cells','Mean ΔReturn pp','Mean 95% interval','Median','Median 95%'],[[P[p],f'{x["positive_cells"]}/{x["negative_cells"]}/{66-x["positive_cells"]-x["negative_cells"]}',n(x['mean_delta_pp']),f'[{n(x["mean_ci95"][0])}, {n(x["mean_ci95"][1])}]',n(x['median_delta_pp']),f'[{n(x["median_ci95"][0])}, {n(x["median_ci95"][1])}]'] for p,x in d['walk_forward']['bootstrap'].items()]))
    add('每個 policy 分開；ticker 與六個時間 fold 各自 multinomial resample，權重相乘，共 4000 replicates。同一 symbol 的不同 policy/fold 不當 iid；沒有普通 t-test。只有 11×6 clusters，interval 是描述性近似，不能當正式顯著性。')
    add('## 5. Test metrics（全部 11 symbols）')
    exp=[r for r in rows if r['design']=='expanding']
    add(md(['Fold','Symbol','Policy','v2 Return','M3 Return','ΔReturn pp','v2 MDD','M3 MDD','ΔMDD pp','v2 Sharpe','M3 Sharpe','ΔSharpe','v2/M3 Exposure','v2/M3 Pos','v2/M3 Turnover'],[[r['fold'],r['symbol'],P[r['policy']],pct(r['test_v2']['total_return']),pct(r['test_m3']['total_return']),n(r['test_delta']['return_pp']),pct(r['test_v2']['max_drawdown']),pct(r['test_m3']['max_drawdown']),n(r['test_delta']['mdd_pp']),n(r['test_v2']['sharpe_ratio']),n(r['test_m3']['sharpe_ratio']),n(r['test_delta']['sharpe']),f'{n(r["test_v2"]["exposure_pct"])}%/{n(r["test_m3"]["exposure_pct"])}%',f'{r["test_v2"]["number_of_positions"]}/{r["test_m3"]["number_of_positions"]}',f'{n(r["test_v2"]["turnover"])} / {n(r["test_m3"]["turnover"])}'] for r in exp]))
    add('CAGR、commission、slippage、實際 train/test trading dates 與完整 train metrics 在 fold machine table。短期 CAGR 只是 API 一致欄位，非決策依據。Expanding/Rolling test 值不重複列，因 raw test 完全相同。')
    add('## 6. Cumulative pseudo-OOS stitching')
    add('只拼 test periods。每個 symbol 每 fold 使用獨立 normalized sleeve；fold 邊界重新等權1/11，fold內權重隨報酬漂移，沒有重複使用共同資金。源模擬各用 $100,000 只是保留 whole-share sizing，再正規化。Median index 非 self-financing，只是描述。這仍是 discovery-sample pseudo-OOS。')
    add(md(['Policy','Index','v2 Return','M3 Return','ΔReturn pp','v2 MDD','M3 MDD','v2 Sharpe','M3 Sharpe'],[[P[p],kind,pct(x[kind]['v2']['total_return']),pct(x[kind]['m3']['total_return']),n(100*(x[kind]['m3']['total_return']-x[kind]['v2']['total_return'])),pct(x[kind]['v2']['max_drawdown']),pct(x[kind]['m3']['max_drawdown']),n(x[kind]['v2']['sharpe']),n(x[kind]['m3']['sharpe'])] for p,x in d['walk_forward']['stitched'].items() for kind in ('equal_weight','cross_symbol_median_index')]))
    add(md(['Policy','Gate-conditioned','Return','MDD','Sharpe'],[[P[p],design,pct(x[design+'_gate_conditioned_equal_weight']['total_return']),pct(x[design+'_gate_conditioned_equal_weight']['max_drawdown']),n(x[design+'_gate_conditioned_equal_weight']['sharpe'])] for p,x in d['walk_forward']['stitched'].items() for design in ('expanding','rolling')]))
    add('Expanding train gate 全 PASS，故其 gate-conditioned index = always-M3。Rolling F2 FAIL，該 fold 用 v2；這使 cumulative improvement 變小。這不是參數選擇，只是事前 frozen deployment gate 的模擬。')
    add('## 7. BreakDayLow mechanism：false vs true breakdown')
    add('固定分類：至少20個 forward sessions；若10日內任一 Close 回到 BreakDayLow 且20D return≥0，為 FALSE；若10日未回復且20D≤−5%或20D min Low≤−10%，為 TRUE；其他及不完整為 MIXED。這些 cutoff 不是交易規則。')
    add(md(['Policy','Events','完整20D','False','True','Mixed','False/完整','True/完整','ΔPnL mean/median','5% loss pp','Worst MAE','Worst add. DD pp'],[[P[p],x['events'],x['complete_classification'],x['classification']['FALSE_BREAKDOWN'],x['classification']['TRUE_BREAKDOWN'],x['classification']['MIXED'],pct(x['classification']['FALSE_BREAKDOWN']/x['complete_classification']),pct(x['classification']['TRUE_BREAKDOWN']/x['complete_classification']),f'${n(x["delta_pnl"]["mean"])} / ${n(x["delta_pnl"]["median"])}',n(x['loss_var95_pp']),pct(x['worst_m3_mae_after_broken']),n(x['worst_additional_marked_drawdown_pp'])] for p,x in d['mechanism_summary'].items()]))
    add('「False 較多」只回答固定價格路徑分類，不等於 M3 已獲廣泛 portfolio 支持。M3 在保守 38 events 中 24 筆較佳、14 筆較差；重大 true/mixed tail 足以抵消部分小幅反彈。')
    add('### 每一個 TEST BreakDayLow event')
    add(md(['Fold','Symbol','Policy','Pos','Entry','Half stop date/level','BreakLow / broken','v2 exit','5/10/20/40D','Class','M3 exit/reason','ΔPnL','Δreturn pp','M3 MAE/MFE','Add.DD pp'],[[r['fold'],r['symbol'],P[r['policy']],r['position_id'],r['entry_date'],f'{r["half_stop_date"]} / {n(r["half_stop_level"])}',f'{n(r["break_day_low"])} / {r["break_broken_date"]}',n(r['v2_exit_price']),'/'.join(pct(r['forward_return_from_v2_exit'][str(q)]) for q in (5,10,20,40)),r['classification'],f'{r["m3_exit_date"]} / {r["m3_exit_reason"]}',f'${n(r["delta_net_pnl"])}',n(r['delta_return_on_entry_cost_pp']),f'{pct(r["m3_mae_after_broken"])} / {pct(r["m3_mfe_after_broken"])}',n(r['largest_additional_marked_drawdown_pp'])] for r in d['mechanism_rows']]))
    add('Execution-level subsequent path、qty、fees、slippage、hash 均保存在 JSON mechanism_rows。Forward return 從 actual v2 sell execution price 到指定交易日 close；缺少 endpoint 保留 null，不當零。')
    add('## 8. Tail risk — worst 10')
    for p,x in d['mechanism_summary'].items():
      add(f'### {P[p]}')
      add(md(['Symbol/Pos','Entry','Half','BreakLow/broken','v2 exit','M3 exit/reason','Additional loss','Δreturn pp','MAE after','Add.DD pp'],[[r['symbol']+'/'+r['position_id'],r['entry_date'],r['half_stop_date'],f'{n(r["break_day_low"])} / {r["break_broken_date"]}',n(r['v2_exit_price']),f'{r["m3_exit_date"]} / {r["m3_exit_reason"]}',f'${n(r["delta_net_pnl"])}',n(r['delta_return_on_entry_cost_pp']),pct(r['m3_mae_after_broken']),n(r['largest_additional_marked_drawdown_pp'])] for r in x['worst_10']]))
    add('最大風險不是平均報酬，而是已剩半倉仍可能延長承受急跌；TSLA 最差案例的 M3 最後只是 test-end 強制結算，表示終點 censoring 仍會低估或高估自然 lifecycle。Tail gate 本輪通過（5% loss與worst marked DD仍在事前限制內），但不抵銷 breadth/LOSO 失敗。')
    add('## 9. Regime stability')
    add(md(['Fold','SPY return','Ann.vol','Trend','Vol class','Cons./Heur./Fav improved'],[[f,pct(x['spy_return']),pct(x['spy_realized_volatility']),x['trend'],x['volatility'],'/'.join(str(next(r['return_improved'] for r in d['regime']['results'] if r['fold']==f and r['policy']==p)) for p in P)] for f,x in d['regime']['fold_labels'].items()]))
    add('六個 test folds 全是事前 +5% 規則下的 uptrend；五個 low-vol、一個 medium-vol，沒有 sideways、downtrend 或 high-vol。這是本輪最嚴重的 regime coverage 限制：不能回答 M3 在熊市是否安全，更不能把牛市下的 false-break比例外推。Regime label 只使用該 test period SPY 當時資料，但作事後描述，不進 gate/entry。')
    add('## 10. SPY / QQQ 獨立檢查')
    etf=[r for r in exp if r['symbol'] in ('SPY','QQQ')]
    add(md(['Fold','ETF','Policy','ΔReturn pp','ΔSharpe','ΔMDD pp'],[[r['fold'],r['symbol'],P[r['policy']],n(r['test_delta']['return_pp']),n(r['test_delta']['sharpe']),n(r['test_delta']['mdd_pp'])] for r in etf]))
    add('SPY/QQQ raw test 在三種 policy 恰好相同，是因這些 fold 的 relevant path 沒有 policy-specific ambiguity，不應重複計為三份獨立證據。ETF 結果比 First TP candidate C 更正面，但 QQQ 在部分 folds 犧牲 MDD，且只有兩檔 ETF。')
    add('## 11. Earlier Historical External Check')
    add(f'Yahoo query2 HTTPS IPv4 probe失敗（curl error 7）；沒有修改 security、建立 proxy/tunnel 或繞過。Frozen common cache 從 2020-12-03 開始，Bias/MA/ATR warm-up 後只剩 {earlier["bars"]} 個策略 sessions：{earlier["actual_common_fully_warmed_period"][0]}～{earlier["actual_common_fully_warmed_period"][1]}。同一 provider/adjustment basis，卻不達事前3年/500 bars門檻。')
    add(md(['Policy','Return improved','Sharpe improved','Median ΔReturn pp','Median ΔMDD pp'],[[P[p],x['return_improved'],x['sharpe_improved'],n(x['median_return_delta_pp']),n(x['median_mdd_delta_pp'])] for p,x in earlier['breadth'].items()]))
    add('結論為 **UNAVAILABLE / INSUFFICIENT**, 不是負面早期驗證。短區間只有一個 symbol 產生正差，無法改變 NOT SUPPORTED，也不允許調整 M3。Survivorship/selection limitation：11 symbols 為今日已知大型科技與ETF，不是2016時點預先選定 universe。')
    add('## 12. Leave-one-symbol-out sanity')
    add(md(['Held out','Other10 gates C/H/F','Heldout ΔReturn C/H/F','ΔSharpe C/H/F','ΔMDD C/H/F','Support policies'],[[r['heldout'],'/'.join('PASS' if r['policies'][p]['other_10_gate_pass'] else 'FAIL' for p in P),'/'.join(n(r['policies'][p]['heldout_return_delta_pp']) for p in P),'/'.join(n(r['policies'][p]['heldout_sharpe_delta']) for p in P),'/'.join(n(r['policies'][p]['heldout_mdd_delta_pp']) for p in P),r['supportive_policies']] for r in d['leave_one_symbol_out']]))
    add('Other-10 gate 在每個 holdout/policy 都 PASS，所以 full-sample evidence 不依賴任何單一 ticker 才成立；但 held-out directional generalization 只有7/11達至少兩種policy。MSFT=0；TSLA/AMD/AVGO=1。NVDA/META 各3，顯示「不是只靠它們」與「尚未廣泛泛化」可同時成立。這是同一 discovery sample 的 cross-sectional sanity，不是 OOS。')
    add('## 13. Decision gate 與 failure criteria')
    add(md(['Requirement','Pass?','Evidence'],[
      ['Test direction',str(dec['core']['direction']),f'positive-fold counts {dec["policy_positive_fold_count"]}; cells {dec["policy_positive_symbol_fold_cells"]}'],
      ['Train gate',str(dec['core']['train_gate']),'Expanding 6/6, Rolling 5/6'],
      ['Tail',str(dec['core']['tail']),f'Conservative p5 {n(mech["loss_var95_pp"])}pp; worst add.DD {n(mech["worst_additional_marked_drawdown_pp"])}pp'],
      ['Leave-one-out',str(dec['core']['leave_one_out']),'7/11 heldouts support >=2 policies; required 8'],
      ['Bootstrap precision for STRONG',str(dec['strong_requirements']['bootstrap_precision']),'All mean intervals cross zero'],
      ['Valid earlier check for STRONG',str(dec['strong_requirements']['valid_earlier_check']),'41 sessions vs required 500']]))
    add('事前只允許 NOT SUPPORTED／PROMISING — NEEDS TRUE FORWARD DATA／STRONG RETROSPECTIVE EVIDENCE — FREEZE AND FORWARD TEST。本輪 core direction 與 LOSO 失敗，所以不是「接近 Strong」；stitched index 較佳不能推翻 gate。')
    add('預先保存但尚未啟動的 failure criteria：\n'+'\n'.join(f'- {x}' for x in d['design']['forward_failure_criteria']))
    add('由於結論 NOT SUPPORTED，不建立 `m3-frozen-spec.md`，也不宣稱進入 forward test。若未來重新提案，必須是新研究決策並重新事前登記，不能把本輪 gate 改鬆。')
    add('## 14. Machine-readable artifacts、limitations 與驗證')
    add('- [完整研究 JSON](../data/m3-retrospective-walk-forward.json)\n- [396-row fold table](../data/m3-retrospective-walk-forward-folds.json)\n- 完整 fold row 包含 requested/actual train/test dates、symbol、policy、v2/M3 metrics、delta、train matched-entry evidence、policy gate、fold gate。')
    add('主要限制：discovery/test overlap；六個 test 全牛市；test-start 強制空倉與 fold-end forced close 的 boundary/censoring；M3事件稀疏、大量tie；11 symbols/6 folds cluster少；同一股票與 policy高度依賴；ETF只有2檔；survivorship/selection bias；Yahoo adjusted OHLC口徑及 volume原值沿用；pseudo-OOS aggregate非可執行portfolio；CAGR年化短樣本不穩定。')
    add(f'計算 {d["runtime_seconds"]:.1f}s。Canonical Simple/Advanced engine replay executions、positions、net PnL、equity、metrics differences均0。資料庫+audits、production source、canonical parquet fingerprint前後一致；既有 research/report/data artifact hashes未變。完整測試與 build 結果另存 validation JSON。')
    return '\n'.join(L).rstrip()+'\n'

if __name__=='__main__':
    import sys;sys.stdout.reconfigure(encoding='utf-8')
    d=json.loads((ROOT/'data/m3-retrospective-walk-forward.json').read_text(encoding='utf-8'))
    f=json.loads((ROOT/d['fold_table_file']).read_text(encoding='utf-8'))
    print(render(d,f),end='')
