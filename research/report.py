"""Render the saved research JSON as a reproducible Markdown report, to stdout."""
import json
import sys
from research import ROOT


def num(v, digits=2):
    return "—" if v is None else f"{v:,.{digits}f}"


def pct(v, digits=2):
    return "—" if v is None else f"{100*v:.{digits}f}%"


def table(headers, rows):
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join("| " + " | ".join(str(v).replace("|", "/") for v in row) + " |" for row in rows)


def label(name):
    return name.replace("ADVANCED_MINUS_", "− ").replace("ADVANCED_FULL", "FULL").replace("_", " ")


def render(d):
    parts=[];add=parts.append
    canon=d["canonical"];full=canon["advanced"]["metrics"];simple=canon["simple"]["metrics"]
    oat=d["one_at_a_time"];matched=d["matched_entry"]
    add("# Advanced Strategy Version 2 — Decomposition / Ablation\n\n2026-09-04。NVDA 2021-09-01～2026-09-01；Conservative；research-only；未做參數 optimization。所有美元比較均包含現有commission/slippage。")
    add("## 1. Executive Summary")
    add(f"Simple總報酬 **{pct(simple['total_return'],8)}**，Advanced **{pct(full['total_return'],8)}**，差 **{num((simple['total_return']-full['total_return'])*100,8)} pp**。Advanced降低了全期間MDD，但付出很大的長趨勢曝險代價。")
    add("主要結論不是『每個confirmation都不好』。在固定進場/P0/Q0比較，Volume與Day2有正的損失保護；主要upside壓縮來自First TP regime家族及其後的減倉/出場，MA Break家族在此樣本也呈負的增量效果。")
    add("- 移除First TP整個家族：總報酬245.767414%，比FULL增加232.379942 pp；MDD由−22.952545%變成−27.629838%。77個固定進場的net PnL合計改善146,956.88美元。這是**家族**效果，不能全部說成『第一次賣50%』的單獨效果。\n- 不重疊的下一個主要家族是MA half-stop＋Break Protection：移除後報酬61.337174%，提升47.949702 pp；固定進場改善41,604.13美元。\n- 單獨移除Protective的原始OAT增益排名第二，但全回測只剩一筆持倉，20個受影響anchors中16個拖至期末。此結果高度依賴終點與未設替代出場，**不是建議取消止損**。\n- Advanced平均收盤股票曝險12.676674%，Simple41.745798%；Advanced平均收盤cash87.323326%。低報酬與低曝險高度相連，但這是規則造成的中介效果，不是可再額外加總的一條因果貢獻。")
    add("### Phase 0 — Frozen canonical baseline")
    add(table(["欄位","Simple","Advanced"],[["Backtest ID",canon['simple']['backtest_id'],canon['advanced']['backtest_id']],["Strategy version",2,2],["Policy","Conservative","Conservative"],*[ [k,num(simple[k],10),num(full[k],10)] for k in ["total_return","cagr","max_drawdown","sharpe_ratio","number_of_positions"]]]))
    add("上表return/CAGR/MDD為原始ratio；其餘章節顯示百分比。固定capital=100,000、allocation=100%、SMA20、Entry Zone +1%～+1.5%、Volume+10%、MA risk1.5%、First TP3%、Bias126×2σ、ATR14×2、Extreme10%Q0/max3、minimum20%Q0、commission0.05%、slippage0.02%，force_close_at_end=true。**沒有測任何其他數值**。")
    add(f"相同OHLCV逐值驗證：{d['shared_data']['bars_in_study']}根回測daily bars＋187根warm-up；完整cache共{d['shared_data']['bars_including_warmup']}根。資料涵蓋2020-12-03～2026-09-01。Parquet SHA256：`{d['shared_data']['sha256']}`。完整request、provider/cache metadata、data coverage、metrics及result SHA256存於[data JSON](../data/advanced-v2-ablation.json)。Simple舊紀錄未保存完整fetch metadata，不補造；本輪共用cache已證實與兩個baseline OHLCV一致。")
    add("重新用目前production engine驗證：兩個baseline executions、prices、quantities、net PnL、equity、metrics完全相同。舊Simple使用NY offset、較新Advanced使用UTC，僅比較時轉同一instant；舊Simple部分entry-zone audit metadata較少。少量gross-reporting浮點尾差在1e−9美元容差內，沒有修改stored gross或任何歷史紀錄。")
    add("## 2. Simple vs Advanced structural differences")
    add(table(["面向","Simple v2","Advanced v2"],[
        ["Entry","共用Entry Zone v2：Open>UpperEntry不追價；High達Upper成交Upper；每日expiry","完全相同"],
        ["MA stop","MA(t−1)×.985，全出","First TP前賣current一半，建立BreakDayLow"],
        ["Break lifecycle","無","次交易日起嚴格跌破BreakDayLow全出；Low>MA(t)於close reset；不買回"],
        ["Validation","無","Day1 volume；pass或research bypass後的Day2嚴格close確認；失敗next-open全出"],
        ["First TP / regime","無；一直使用同一MA全出","一次current半數TP；first flag也使原MA風控退出，轉Protective regime"],
        ["Protective","無P0 floor","max(P0,MAprev×.985)全出；含同日新啟用stop的conservative順序"],
        ["Extreme","無","FirstTP後Bias/ATR OR，獨立edge，10%Q0/max3/20% gate"],
        ["Data readiness","需要MA history","額外需要126 completed bias及ATR history；本輪全部已warm-up"],
        ["Accounting / price path","同一whole-share/cost/Conservative/end-close","相同，但Advanced多threshold會產生額外ambiguity情境"]]))
    add("Advanced不是Simple把modules全關。研究ADVANCED_CORE只有同樣entry＋持有至期末；沒有暗中替它塞回Simple MA全出。所有新程式在research/，production不import；all-on parity及77 anchors完整lifecycle parity是硬性測試。")
    add("### 合法modules與dependency")
    add("Volume off只waive量能gate，仍保存Day1 close供Day2；Day2 off只移除Day2 gate。MA Break off只移除pre-First-TP half/Break/reset，不移除Protective公式內MA。First TP family off同時關閉FirstTP regime、Protective、Bias、ATR。FirstTP已開而Protective未開的bridge stage，仍停止舊MA loop，因此可能只剩confirmation或期末平倉；明確標示，不假裝是production可選策略。Bias/ATR各自可關，但不能在FirstTP關閉時啟用。")
    add("## 3. One-at-a-time removal")
    add("括號為variant−FULL delta；百分比欄delta是percentage points（pp），不是相對百分比。所有共同指標使用現有production metrics；新增的曝險/episode統計另標定義。")
    def cell(row,key,percent=False):
        v=row['summary'][key];delta=row['delta_vs_full'][key]
        return f"{pct(v) if percent else num(v)} ({num(delta*100 if percent and delta is not None else delta)})"
    add(table(["Variant","Return% (Δpp)","CAGR% (Δpp)","MDD% (Δpp)","Sharpe (Δ)","Positions (Δ)","Win% (Δpp)"],[[label(r['name']),cell(r,'total_return',True),cell(r,'cagr',True),cell(r,'max_drawdown',True),cell(r,'sharpe_ratio'),cell(r,'number_of_positions'),cell(r,'win_rate',True)] for r in oat]))
    add(table(["Variant","Avg trade% (Δpp)","Median% (Δpp)","PF (Δ)","Holding days (Δ)","Exposure days% (Δpp)","Commission$ (Δ)","Slippage$ (Δ)"],[[label(r['name']),cell(r,'average_trade_return',True),cell(r,'median_trade_return',True),cell(r,'profit_factor'),cell(r,'average_holding_days'),cell(r,'exposure_pct'),cell(r,'total_commission'),cell(r,'estimated_slippage_cost')] for r in oat]))
    add("Holding days為production的calendar days；Exposure days為當天曾持有的trading-day比例。PF=999是現有engine在無虧損但有獲利時的sentinel，不能當作穩健的估計。")
    add("## 4. Progressive bridge")
    add(table(["累積stage","Return","CAGR","MDD","Sharpe","Positions","Return增量pp","MDD增量pp"],[[label(r['name']),pct(r['summary']['total_return']),pct(r['summary']['cagr']),pct(r['summary']['max_drawdown']),num(r['summary']['sharpe_ratio']),r['summary']['number_of_positions'],num(r['delta_vs_previous']['total_return']*100) if r['delta_vs_previous'] else '—',num(r['delta_vs_previous']['max_drawdown']*100) if r['delta_vs_previous'] else '—'] for r in d['progressive_bridge']]))
    add("CORE第一筆在2021-10-14進場且量能/Day2都pass，沒有其他risk module便一直持有；所以最初加Volume/Day2的增量是0，**不代表confirmation無效**。加入MA後才建立更多重複entry機會。+FirstTP stage同時引入regime switch、停止pre-TP MA loop，因此不能把其增量單獨歸因於賣50%。再加入Protective會恢復post-TP全出機制；bridge是條件式、順序依賴的效果，不與OAT結果相加。")
    add("## 5. Matched-entry counterfactual")
    add("固定77個canonical Advanced entry日期、actual P0、Q0及同一行情。每個run只模擬該position直到自行出場或期末；不允許再entry。FULL逐筆成交與原historical lifecycle完全一致。ΔPnL=without−FULL，正值表示該rule在此anchor少賺。此處資金獨立，lifecycles會重疊，合計數字**不是可實現的portfolio PnL/return**。")
    add(table(["Removal","changed /77","ΣΔPnL$","Mean Δ$ /77","Median Δ$ /77","Mean Δ$ changed only","Mean holding Δdays","changed CF期末平倉"],[[label(name),m['changed_anchors'],num(m['sum_delta_pnl']),num(m['delta_pnl_without_minus_full']['mean']),num(m['delta_pnl_without_minus_full']['median']),num(m['changed_only_delta_pnl']['mean']),num(m['mean_holding_days_delta']),m['changed_cf_terminal_closes']] for name,m in matched['summary'].items()]))
    add("未受影響anchors佔多數，因此全77筆median普遍是0，不等於沒有影響。移除Protective的16/20個changed lifecycle只有END_OF_BACKTEST，屬end-date/terminal-horizon敏感結果。其他列的changed CF均不是期末才強制結束。每一筆的FULL/CF PnL、exit、holding delta、MFE/MAE、原exit後5/10/20/40D return見附錄與JSON。")
    add("## 6. Event attribution")
    add("Realized effect定義為該SELL已實現的execution-price PnL，扣本筆sell commission及按sold/Q0分攤的buy commission；它是booked accounting，**不是因果增值**。所有事件合計對上Advanced net PnL。聯合Bias+ATR成交独立列出一次，避免double count。")
    events=d['event_attribution']
    add(table(["Event","count","positions","avg booked net$","median booked net$","sum booked net$"],[[k,v['event_count'],v['positions_affected'],num(v['booked_net_pnl']['mean']),num(v['booked_net_pnl']['median']),num(v['total_booked_net_pnl'])] for k,v in events.items()]))
    add("下表每格為mean / median / N，return從actual SELL execution price算至第N個未來交易日close；正值代表賣後股價上漲。純underlying event-day-close基準的相同統計亦存JSON；兩者勿混用。缺少未來日線時為null，不下載或補造。")
    add(table(["Event","5D mean/median/N","10D","20D","40D"],[[k,*[f"{pct(v['forward_from_execution'][str(n)]['mean'])} / {pct(v['forward_from_execution'][str(n)]['median'])} / {v['forward_from_execution'][str(n)]['n']}" for n in [5,10,20,40]]] for k,v in events.items()]))
    add("### 七個事件問題的回答\n\n1. **Volume fail後不通常立即續跌**：43次的5D median +1.87%，62.79%上漲；20D median +1.50%。但固定entry全lifecycle顯示保留Volume合計多2,176.81美元，保護少數尾部風險；不能只看反彈率下結論。\n2. **Day2 fail有短線保護證據**：12次5D median −3.88%，75%下跌；20D median已回到+2.59%。固定entry保留Day2多9,987.42美元。\n3. **MA half-stop後常短線反彈**：28次5D上漲64.29%，median +1.77%；20D median +4.63%。不等於已證明絕對局部最低點，但與移除MA family固定entry改善41,604.13美元一致。\n4. **BreakDayLow單獨樣本不足**：僅2次，20D兩次均上漲；本輪C把half＋Break合併，不把family整體效果全歸給BreakDayLow。\n5. **First TP會截短winner曝險**：11次實際FirstTP後10D median +5.38%，所有FirstTP都有booked profit，但後續趨勢收益仍會被削掉。另有9次FirstTP flag在adverse-first下未做favorable partial而直接Protective全出；因此家族效果不只是一刀50%。\n6. **Extreme增加booked realized profit，不代表增加總profit**：移除全部Extreme，8個affected anchors合計多33,079.49美元，而且holding-days delta=0，較乾淨地指向同一exit前winner exposure被削減。Bias/ATR OR共用max3，個別效果不可相加。\n7. **Protective有保護機制但效果不能只靠長期反事實排序**：20次exit的booked median −63.28美元，breakeven P0並不保證扣費後獲利；20D median −2.04%。然而無Protective會大幅延長持倉至期末，其長期收益受NVDA上漲與截尾支配，不能據此建議刪除。")
    add("## 7. Winner truncation")
    win=d['winner_truncation']
    add(f"Simple只有 **{win['available_profitable_or_losing_positions']}** 筆profitable positions；top20實際列全部15筆，不用5筆虧損補滿。Primary matching採Simple自己的entry/P0/Q0強制isolated Advanced lifecycle，這是counterfactual，**不是實際Advanced成交**。另外列出時間重疊的actual Advanced IDs，僅作market episode對照。Actual dollar PnL受不同capital影響，不能直接因果相減。")
    add(table(["範圍","available","Simple ΣPnL$","same-entry Advanced ΣPnL$","差額$"],[[f"Top{k}",v['available'],num(v['simple_pnl_sum']),num(v['advanced_same_entry_pnl_sum']),num(v['advanced_minus_simple_sum'])] for k,v in win['aggregates'].items()]))
    add(table(["Simple ID","Entry→Simple exit","Simple PnL$","Advanced same-entry PnL$","第一個降低曝險的rule","不含該rule potential$","actual Advanced episode MTM$","actual Advanced overlap IDs"],[[r['simple_position_id'],r['entry_date'][:10]+' → '+r['simple_exit_date'][:10],num(r['simple_pnl']),num(r['advanced_same_entry_pnl']),r['first_exposure_reduction'],num(r['potential_pnl_without_first_rule']),num(r['actual_advanced_equity_change_in_simple_calendar_interval']),', '.join(r['actual_advanced_overlapping_position_ids'])] for r in win['rows']]))
    add("Actual episode MTM是canonical Advanced在Simple entry前一交易日close至Simple exit close的equity差，包含該時間窗內全部交易及未實現變動；不是重疊positions完整生命周期PnL的相加。它與same-entry counterfactual分欄，且因不同capital不能作直接因果差額。")
    add("最重要的三個episode：\n\n- Simple position-27（2024-01-05）：Simple +150,352.28；同Q0 Advanced +38,014.15。FirstTP首先減曝險；移除其家族後potential +148,769.69，後續exit日期不同，詳JSON。實際Advanced position-31的資金/股數較小，不能拿它的PnL當同Q0結果。\n- Simple position-47（2025-04-25）：Simple +135,331.02；matched Advanced同日因FirstTP/Protective的Conservative路徑全出，−255.12。移除Protective後也只到+3,656.42，因其他confirmation很快接手出場。**第一個rule不是全部lost-upside的唯一原因**。\n- Simple position-21（2023-04-28）：Simple +72,147.77；matched Advanced量能fail出場後僅+1,000.96。只移除Volume仍僅+2,196.17，顯示downstream exits的interaction。")
    add("Simple top10獲利合計505,555.14美元，但全策略淨利只有147,507.25美元，因其餘positions有大量虧損。少數大winner對總績效確實至關重要。上表固定anchor sums不屬於一個可同時持有的策略資金曲線，也不能直接解釋成134,119.78美元canonical gap的可加總分解。")
    add("## 8. Loss prevention")
    loss=d['loss_prevention'];tot=loss['aggregates']['10']
    add(f"Simple worst10損益合計{num(tot['simple_pnl_sum'])}美元；同entry/P0/Q0的Advanced lifecycle為{num(tot['advanced_same_entry_pnl_sum'])}，改善{num(tot['advanced_minus_simple_sum'])}。這證明loss protection確有價值，但與winner表採獨立counterfactual，不能把兩個sum直接轉成年化報酬。")
    add(table(["Simple ID","Entry","Simple loss$","Advanced same-entry$","改善$","首先降低曝險","移除此rule後$"],[[r['simple_position_id'],r['entry_date'][:10],num(r['simple_pnl']),num(r['advanced_same_entry_pnl']),num(r['advanced_minus_simple_pnl']),r['first_exposure_reduction'],num(r['potential_pnl_without_first_rule'])] for r in loss['rows']]))
    add("例如Simple position-42在2025-01-21進場後虧29,774.87；matched Advanced量能fail次日以較高open全出，獲利10,611.16；只移除Volume則變−9,581.86。Volume在此有明確保護作用。另一方面position-46兩者同樣遇到隔日gap，結果相同；不能聲稱confirmation防得住所有跳空。")
    add("## 9. Drawdown attribution")
    add(table(["Variant","MDD","start","trough","recovery"],[["Simple",pct(simple['max_drawdown']),simple['max_drawdown_start'],simple['max_drawdown_bottom'],simple['recovery_date'] or 'null'],*[[label(r['name']),pct(r['summary']['max_drawdown']),r['summary']['max_drawdown_start'],r['summary']['max_drawdown_bottom'],r['summary']['recovery_date'] or 'null'] for r in oat]]))
    add("FULL最深回撤在2021-11-29～2023-10-18；Simple最深在2024-10-21～2025-04-16。不能把兩個不同時段的MDD差直接當某rule的收益。以下使用Simple主要回撤的同一calendar窗口；每格為窗口首日至trough報酬 / 窗內MDD。")
    for window in d['drawdown_common_calendar_windows']:
        ep=window['simple_episode'];add(f"### {ep['start']} → {ep['trough']}")
        add(table(["Variant","窗口return","窗內MDD"],[[label(k),pct(v['peak_to_simple_trough_return']),pct(v['within_window_mdd'])] for k,v in window['variants'].items()]))
    add("2024-10～2025-04的窗內MDD：FULL−19.10%，無Volume−27.20%，無MA Break−22.77%。所以MA Break即使全期增量不佳，仍對這段熊市有保護；不能因全期MDD僅差0.09pp便說從沒用。2021-11～2023-01則無MA Break窗內MDD−16.19%，FULL−21.07%，方向相反。Volume的下行保護在2025窗口更清楚。各variant最差五個非重疊underwater episodes完整存JSON，recovery=null表示截至研究終點尚未回復。")
    add("全期OAT：FirstTP family的MDD改善4.68pp，Volume4.37pp、Day2 1.60pp；Bias1.54pp、全部Extreme1.00pp。family/子模組重疊，不可相加。Protective在bridge中從−39.93%改善至−23.95%，與FULL-context OAT不同，是條件與path dependence的實例。")
    add("## 10. Capital / exposure effects")
    ex=d['exposure']
    add(table(["指標","Simple","Advanced"],[[k,num(ex['simple'][k],6),num(ex['advanced'][k],6)] for k in ex['simple']]))
    add("定義：time_in_market是当日曾持股的day-count proxy，日OHLC無法給精確盤中時間；average_close_capital_exposure是每日收盤market value/equity的平均，cash=1−exposure。positive-close Q/Q0只在收盤仍持股時計算（Simple100%，Advanced39.75%）；另一when_exposed版本包含當日全出後的0。Average entry notional/shares受不同capital path和股價水準影響。Turnover採双邊買賣gross notional/平均equity，另除期間年數年化。")
    add("Advanced不是單純『進場少』：它有77次entry，Simple63次，但持倉天數較短、剩餘部位更小。股票收盤曝險只有Simple的約30.37%；cash高約29.07pp。無FirstTP family時平均close曝險31.30%，無全部Extreme時16.92%，支持regime/減倉造成低曝險的解釋。Advanced絕對fees較少但normalized turnover較高，不是交易成本主導這個134.12pp報酬差。")
    add("## 11. Rule ranking")
    add("符號：Return contribution=FULL−without（pp）；MDD reduction=FULL MDD−without MDD（正值代表FULL較淺）；matched contribution=PnL_FULL−PnL_without（美元）。Winner upside removed為15個Simple winner anchors中without−FULL，正值表示削掉upside。Loss prevention為10個Simple loser anchors中FULL−without。它們是不同控制集，不能彼此相加。")
    categories={"A_ADDS_VALUE":"A 明顯增加價值","B_TRADE_OFF":"B 有trade-off","C_NEGLIGIBLE":"C 幾乎沒影響","D_DRAG":"D 此樣本拖累","E_SAMPLE_LIMITED":"E 樣本/終點限制"}
    add(table(["Rule removed","分類","Return貢獻pp","MDD改善pp","matched PnL貢獻$","changed /77","winner upside removed$","loss prevention$"],[[label(r['variant']),categories[r['category']],num(r['return_contribution_pp']),num(r['mdd_reduction_contribution_pp']),num(r['matched_pnl_contribution']),r['matched_changed_anchors'],num(r['winner_upside_removed_sum']),num(r['loss_prevention_sum'])] for r in d['rule_ranking']]))
    add("分類為描述性screen，不是統計顯著性：changed<5，或單筆full-path且>50%changed CF期末平倉→E；|return|<1pp、|MDD|<1pp且|Σmatched|<1000→C；return/MDD/matched一致改善→A，一致惡化→D，其餘→B。本樣本沒有符合A或C的module。BreakDayLow單獨僅2次，不能從MA family排名推斷其單独效果。Protective雖然原始數字看似拖累，16個terminal closures使它歸E，避免把期末長抱收益當作可靠排序。")
    add("### 最後A～G回答\n\nA. 最大報酬拖累是**First TP regime家族**，OAT移除提升232.38pp，固定Advanced anchors改善146,956.88美元；不能全部歸因單次50% sale。\nB. 原始OAT第二是Protective（+178.30pp），但它屬於A家族、且terminal-horizon受限。若要求非重疊且更可解讀的下一個家族，是**MA half-stop＋Break Protection**（+47.95pp）。\nC. 全期OAT的MDD保護以FirstTP family +4.68pp最大；單一confirmation以**Volume +4.37pp**最有一致的下行證據，尤其2025窗口。\nD. 沒有可穩健稱『完全沒增量價值』的module。Bridge初期Volume/Day2的0是單筆持有路徑，不代表無效；BreakDayLow和部分Extreme樣本少。\nE. Simple讓少數大winner保留更完整曝險；Advanced較早exit/partial、更多cash、再entry後資金路徑更小，winner truncation壓過其loss protection。\nF. 主要是**FirstTP後的regime/提前出場＋partial減倉造成低曝險**；confirmation也犧牲部分趨勢，但固定entry顯示有保護，不是最大的獨立拖累。\nG. 下一階段先研究**FirstTP家族內的『50% sale vs protective activation/Conservative同日路徑』互動**，再研究**MA half-stop／Break Protection**。先做語意清楚的分解與其他市場/時段驗證，不直接改production或開始調參。")
    add("## 12. Caveats / reproducibility")
    add("1. 單一股票、單一五年樣本、同一行情cache；不是out-of-sample結論。沒有optimization、walk-forward或新production策略。\n2. Ablation只是假設移除rule，marginal effects不具可加性；OAT、bridge、matched所控制的條件不同。\n3. Counterfactual lifecycles可重疊且延伸至Simple episode以後；不共享capital、不重建portfolio return。終點平倉高度敏感的Protective-off單列限制。\n4. Winner/loser selection本來就是事後選樣，只用診斷winner truncation，不能當交易訊號。Simple只有15個winners。\n5. MFE/MAE沿用production daily High/Low envelope，包含entry/exit整日，並非精確持有時間內的可成交最大收益。\n6. Forward returns是completed future closes的描述性結果，不是rule因果效果；缺失horizon為null，N隨horizon不同。\n7. Event booked PnL和直接移除module的counterfactual PnL是不同概念；聯合Bias/ATR只計一次。\n8. 比較舊timestamp僅normalize表示法，不改資料；舊Simple事件metadata新增欄位與成交差異分開。\n9. Production指標定義原樣保留（包含holding calendar days及PF sentinel）；不藉研究修正metrics、cost或execution。\n10. 排名不是顯著性檢定；極端少數交易/市場period影響很大。報告不建議直接移除風控。")
    add("### 測試與不變性\n\n19項research tests包含兩個production baseline replay、ALL-ON exact execution/equity、77個canonical anchors完整lifecycle、dependency拒絕、各disabled module不漏event、固定entry不再進場、forward horizon與immutable fingerprint。最終實測：research 19 passed、backend 142 passed（2個既有dependency warnings）、frontend 17 passed。JSON重新產生後，除實測runtime外與保存內容完全一致。研究輸出命令：`backend\\.venv\\Scripts\\python.exe -B -m research.run_ablation`；report命令：`backend\\.venv\\Scripts\\python.exe -B -m research.report`；兩者只stdout、不寫DB。")
    add(f"DB+audits SHA256 before/after：`{d['immutability']['before']['database_and_audits']}`。Production app source：`{d['immutability']['before']['production_source']}`。完整資料fingerprints前後一致。既有executions、quantities、net PnL、equity、metrics differences=0。")
    add("## 附錄A：77 anchors的FULL基準及原出場後forward returns")
    add(table(["ID","Entry","P0","Q0","FULL net$","FULL exit","MFE","MAE","5D","10D","20D","40D"],[[r['position_id'],r['entry_date'][:10],num(r['entry_price'],6),r['q0'],num(r['full']['net_pnl']),r['full']['final_exit_date'][:10],pct(r['full']['maximum_favorable_excursion']),pct(r['full']['maximum_adverse_excursion']),*[pct(r['forward_from_original_exit'][str(n)]) for n in [5,10,20,40]]] for r in matched['rows']]))
    add("## 附錄B：每個fixed-entry counterfactual\n\nFULL PnL/date見附錄A；下表Δ=without−FULL。所有P0/Q0固定。")
    for name in matched['summary']:
        add(f"### {label(name)}")
        add(table(["Anchor","CF net$","ΔPnL$","CF exit","CF exit reason","holding Δdays","CF MFE","CF MAE"],[[r['position_id'],num(r['counterfactuals'][name]['net_pnl']),num(r['counterfactuals'][name]['delta_pnl_without_minus_full']),r['counterfactuals'][name]['exit_date'][:10],r['counterfactuals'][name]['exit_reason'],r['counterfactuals'][name]['holding_days_delta'],pct(r['counterfactuals'][name]['mfe']),pct(r['counterfactuals'][name]['mae'])] for r in matched['rows']]))
    return "\n\n".join(parts)+"\n"


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    report=json.loads((ROOT/"data/advanced-v2-ablation.json").read_text(encoding="utf-8"))
    print(render(report))
