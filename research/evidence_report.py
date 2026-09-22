"""Deterministic Traditional Chinese report, rendered from saved evidence."""
import json
from research import ROOT

NAMES={'A':'Advanced v2 Full','B':'不做 First TP 50% 減碼','C':'不做任何獲利減碼','D':'First TP 改為 25%','E':'不做 Extreme TP',
       'M1':'移除整個 MA Break family','M2':'只保留半倉停損（隔日可再觸發）','M3':'保留半倉／追蹤／重置，關閉 BreakDayLow 出場'}
POL={'conservative':'保守','ohlc_heuristic':'OHLC 推估','favorable':'有利'}

def num(x,n=3):return '—' if x is None else f'{x:,.{n}f}'
def pct(x,n=2):return '—' if x is None else f'{100*x:,.{n}f}%'
def interval(a):return f'[{num(a[0])}, {num(a[1])}]'
def table(headers,rows):
    clean=lambda v:str(v).replace('|','／').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+['| '+' | '.join(clean(v) for v in row)+' |' for row in rows])

def render(d):
    lines=[]
    def add(s=''):lines.extend([s,''])
    def stats(k,p='conservative'):return d['matched_statistics'][k][p]
    def breadth(k,p='conservative',per='FULL'):return next(r for r in d['breadth'] if (r['candidate'],r['policy'],r['period'])==(k,p,per))
    add('# PRE-V3 EVIDENCE GATE')
    add('研究日期：2026-09-05。僅研究／diagnostic；沒有修改 production Advanced v2、執行政策、歷史回測、audits、PnL 或 equity。沒有參數搜尋，沒有建立 v3，也沒有執行 walk-forward。')
    add('## 1. Executive Summary 與 A–I 回答')
    c=stats('C'); b=stats('B'); m1=stats('M1'); m3=stats('M3')
    add('結論：保留正式 v2。只有 M3（保留 MA 半倉停損、BreakDayLow 追蹤與重置，但停用 BreakDayLow 全出場）通過本報告指定五候選中的探索性 walk-forward 門檻，證據為 MODERATE，並非 production 推薦。')
    add(table(['問題','資料支持的回答'],[
        ['A. 取消 50% 減碼是否由少數大贏家驅動？',f'是，正面均值高度右尾集中：B 前 3／5／10 筆占淨改善 {pct(b["concentration"]["top_contributions"]["3"]["fraction_of_net_improvement"])}／{pct(b["concentration"]["top_contributions"]["5"]["fraction_of_net_improvement"])}／{pct(b["concentration"]["top_contributions"]["10"]["fraction_of_net_improvement"])}；C 為 {pct(c["concentration"]["top_contributions"]["3"]["fraction_of_net_improvement"])}／{pct(c["concentration"]["top_contributions"]["5"]["fraction_of_net_improvement"])}／{pct(c["concentration"]["top_contributions"]["10"]["fraction_of_net_improvement"])}。並非只由 NVDA/META 支撐，但剪尾後均值轉負。'],
        ['B. 25% 是否較穩健？','風險／曝險取捨較溫和，並非已證實泛化較好：D 的跨期支持只有 3/6 cells，平均配對效果區間跨零；不能把曝險梯度解讀成報酬必然單調。'],
        ['C. 個股 vs ETF？','有明顯樣本內差異：B/C/D/E 對九個個股的中位 portfolio delta 為正，SPY/QQQ 的 Return、Sharpe delta 在三種 policy 下皆較差；只有兩檔 ETF，不能推論全體 ETF。'],
        ['D. 哪些進場特徵？','低波動／低 ATR 組的 C 平均效果較弱，但趨勢、動能、波動、ATR 分組都不單調；控制 ticker 後，六個預先指定係數的不確定區間皆跨零。沒有足夠證據建立「強趨勢／高波動才取消減碼」的新條件。'],
        ['E. MA family 跨股票仍拖累？',f'報酬方向是：M1 三種 policy 提升 Return 的股票數為 11／9／10，中位 delta +26.70／+15.38／+19.01 pp；配對平均 +{num(m1["bootstrap"]["pooled_entry_point"]["mean"])} pp，區間 {interval(m1["bootstrap"]["two_way"]["mean_ci95"])}。但整組移除帶來明顯回撤尾端風險。'],
        ['F. 半倉還是 BreakDayLow 更值得質疑？','配對報酬改善主要在整個半倉／episode機制，M1 明顯大於只關 BreakDayLow 的 M3；然而保留半倉、只關 BreakDayLow 的 M3 在 portfolio 回撤／換手上更可取。M2 的重複半倉語意不能當純半倉效果；不把兩者差額宣稱為可加總因果貢獻。'],
        ['G/H. 是否值得 walk-forward、最多 1–2 個？','僅推薦 M3 進入事先設計的、非調參的探索性 walk-forward 驗證。M3 配對平均 95% 區間仍跨零，不能稱已證實有效。E 亦通過相同探索性 screens，但不在使用者指定的五候選主矩陣；列為補充，不擴增本輪推薦。'],
        ['I. 是否建立 v3？','不要建立 production v3。通過研究 gate ≠ 上線許可；B/C/D 與 M1 均未通過所有必要 screens。']]))
    add('## 2. 凍結資料、共同樣本與候選')
    add(f'11 symbols、相同 Yahoo daily OHLC、相同成本與 v2 Entry Zone；{d["counts"]["new_ma_portfolios_including_full"]} 次新 MA 結構回測（含 99 個 Full 重播）、沿用 495 個既有 First TP 結構結果，合計 {d["counts"]["unique_portfolios"]} 個不重複 portfolio 設定。這些不是 792 個獨立統計樣本。')
    add('Full：2021-09-01～2026-09-01；A：2021-09-01～2023-12-31；B：2024-01-01～2026-09-01。所有 symbols 都有共同完整區間，1442 根資料、187 根 warm-up、1255 根期間日線。子期間各自重新從相同初始資金、空倉開始；不與 Full 的交易混為額外獨立樣本。')
    add(table(['Canonical','Backtest ID','Return','CAGR','MDD','Sharpe','Positions'],[[k,v['backtest_id'],pct(v['summary']['total_return']),pct(v['summary']['cagr']),pct(v['summary']['max_drawdown']),num(v['summary']['sharpe_ratio']),v['summary']['number_of_positions']] for k,v in d['canonical'].items()]))
    req=d['canonical']['advanced']['request']
    add(f'初始資金 ${req["initial_capital"]:,.0f}；部位 {req["position_size_pct"]}%；手續費 {req["commission_pct"]}%；滑價 {req["slippage_pct"]}%；參數完整保存在 JSON canonical.request，與前輪完全相同。')
    add('Adjustment：所有輸入由前輪正式 Yahoo/cache 流程凍結，未重抓。既有 metadata 名稱 `adjusted_for_splits` 並不完整描述實作：現有 provider 以 adjclose/raw-close 比例調整 OHLC（包含股息調整效果），volume 保留 Yahoo 原值；本研究維持此一致基礎，沒有再加入股息現金流。不能把不同調整口徑的資料混入。檔案與內容 hash、更新時間均在 data_manifest。')
    add(table(['候選','結構'],[[k,NAMES[k]] for k in NAMES]))
    for k,definition in d['design']['ma_variants'].items():add(f'- **{k}**：{definition}')
    add('M2 每日最多一次 current qty 半倉、隔日重新 eligible（即使仍低於新 MA stop），不追蹤 BreakDayLow；不影響量能／Day2 旗標與 First TP 後的正式風控。這是清楚定義的 research semantics，不是修正 production 或無狀態的任意重複賣出。M3 的被停用 BreakDayLow exit 也不參與 favorable/adverse 排序，其他正式政策分支不變。')
    add('## 3. Matched-entry 設計與統計不確定性')
    add('每個 symbol 的 Full Conservative portfolio entry 為 anchor，共 800 筆。三種 policy 各自從相同 entry 日期、actual execution price P0、Q0、市場路徑起算，禁止新 entry；每一筆比較 7 個替代結構，共 16,800 行。它們不是 16,800 個獨立觀察。Full 在替代 policy 下也是同一固定 anchor lifecycle，不偷換成該 policy 自然 portfolio 的另一筆 entry。')
    add('主要配對單位：`delta_return_on_entry_cost_pp = 100 × (PnL_candidate − PnL_full) / (buy execution gross value + buy commission)`。前輪 entry-notional 分母沒有買入佣金；本輪依需求改用完整 entry cost，所以百分比略有縮小，原始 PnL 與 executions 完全不變。正 delta 表示替代候選較佳。')
    add('`delta_exposure_days` = 候選與 Full 的每日收盤 qty/Q0 加總差（等效滿倉交易日），另保留 any-exposure sessions；holding days 為 calendar days。MFE/MAE 是該 lifecycle 已實現的日 High/Low excursion（非進場特徵），MAE delta > 0 代表較不負；不是部位加權損益。日 OHLC 無法精確排除 entry 前／exit 後 extrema，沿用正式 reporting 定義。')
    add('採 ticker × 同步半年度 market episode 的 two-way pigeonhole bootstrap：獨立重抽 ticker 與半年度，再把權重相乘；同一 anchor 的候選共用權重，三種 policy 分開估計。4000 replicates、固定 seed 20260904、95% percentile interval。另列 ticker-only 與 equal-ticker-weighted mean。方法依據 [Owen (2007)](https://arxiv.org/abs/0712.1111) 與 [Owen & Eckles (2012)](https://arxiv.org/abs/1106.2125) 的交叉 cluster 重抽樣設計；本文的股票／時段應用與 percentile intervals 不承接論文為本資料保證精確 coverage。')
    add('只有 11 ticker clusters、11 個含頭尾不完整的日曆半年 episodes，且跨 episode 的持倉仍可能相關。這是有限樣本的近似敏感度分析，不是 iid t-test、不代表已證明正效益；沒有把不顯著當無效果。大量不受模組影響的零 delta 會讓 median 及其區間都是零，應同時看 changed-only 與右尾。')
    rows=[]
    for k in ('B','C','D','E','M1','M2','M3'):
        for p in POL:
            s=stats(k,p); b=s['bootstrap']
            rows.append([k,POL[p],num(b['pooled_entry_point']['mean']),interval(b['two_way']['mean_ci95']),num(b['pooled_entry_point']['median']),interval(b['two_way']['median_ci95']),interval(b['ticker_only']['mean_ci95']),num(b['equal_ticker_mean']),num(s['concentration']['sum_delta_pnl'],2)])
    add(table(['候選','Policy','配對 mean pp','兩向 mean 95%','median pp','median 95%','ticker-only mean 95%','equal-ticker mean pp','配對 ΔPnL $'],rows))
    add('First TP 的 ticker-only 區間較容易全部在零以上；加入同步市場 episode 後 B/C/D/E 的 Conservative mean 區間都跨零。忽略跨股票共同時段依賴會讓結論顯得過於確定。')
    add('## 4. Winner concentration 與剪尾敏感度')
    rows=[]
    for k in ('B','C','D','E','M1','M2','M3'):
        c=stats(k)['concentration']
        rows.append([k,num(c['sum_delta_pnl'],2),*[pct(c['top_contributions'][str(n)]['fraction_of_net_improvement']) for n in (1,3,5,10)],num(c['changed_only']['median']),f'{c["changed_only"]["positive"]}/{c["changed_only"]["negative"]}'])
    add(table(['候選','淨配對改善 $','Top1/淨','Top3/淨','Top5/淨','Top10/淨','changed-only median pp','有利/不利筆數'],rows))
    add('Top-N 按正的 dollar delta 排序，分母為所有正負 delta 淨和；超過 100% 表示其餘交易把改善抵銷。淨和 ≤ 0 顯示 —；JSON 同時提供以「所有正改善總和」為分母的穩定占比。美元金額受 canonical Q0／資金路徑影響，不能視為合併 portfolio 可實現績效；下表改用 entry-cost normalized return。')
    rows=[]
    for k in ('B','C','D','E','M1','M2','M3'):
        c=stats(k)['concentration']
        fields=('without_each_symbol_largest_full_winner','without_each_symbol_largest_delta','without_nvda_meta','winsorized_5_95','trimmed_5_each_tail')
        rows.append([k,*[num(c[f]['mean']) for f in fields],*[num(c[f]['median']) for f in fields[:3]]])
    add(table(['候選','移除各 symbol 最大 Full winner mean','移除各 symbol 最大 Δ mean','移除 NVDA/META mean','5/95 winsor mean','雙尾各5% trim mean','drop winner median','drop Δ median','除 NVDA/META median'],rows))
    add('B/C/D/E：移除各 symbol 最大 Full winner 或最大 delta 後平均仍正、median 仍零；但 winsor/trim mean 為負。C 只有 39/800 筆正 delta，因此 5% 上尾處理幾乎移除全部正效果；這不是尾端失真應被刪除的證據，而是收益機制確實依靠稀少右尾。不能用剪尾後轉負反向宣稱策略應保留全部減碼。M1 的 mean 在這些敏感度分析中仍為正，集中度顯著較低。')
    add('## 5. 個股 vs SPY/QQQ')
    add(table(['候選','群組','股票數','Portfolio ΔReturn pp','ΔSharpe','ΔMDD pp','配對 mean pp','配對 median pp','配對筆數'],[[r['candidate'],r['group'],r['symbols'],num(r['portfolio_median']['return_pp']),num(r['portfolio_median']['sharpe']),num(r['portfolio_median']['mdd_pp']),num(r['matched_return_pp']['mean']),num(r['matched_return_pp']['median']),r['matched_return_pp']['n']] for r in d['asset_groups'] if r['policy']=='conservative']))
    add('Conservative C：679 個個股 anchors 有 35 筆改善、62 筆受損；121 個 ETF anchors 僅 4 筆改善、12 筆受損。個股的少數右尾足以抵銷更多小幅受損，但這兩檔 ETF 的同樣曝險保留沒有產生足夠右尾補償。這是 selected universe／期間的 empirical attribution，不是成長股或 ETF 的因果定律；ETF 與 ticker、波動、成分股高度重疊，且沒有納入存活者以外的隨機 universe。')
    add('其餘 policy 的同口徑分組表保存在 JSON asset_groups；不要把三個 policy 的群組 n 相加。')
    add('## 6. 進場可觀測特徵、異質性與診斷模型')
    add(table(['特徵','完整定義','缺值 entries'],[[k,v,d['feature_missing'][k]] for k,v in d['design']['features'].items()]))
    add('只有 P0 用成交當下已知價格；OHLCV、指標、SPY/QQQ 對照均只用 <=t-1。6 個早期 entries 沒有足夠 200 日歷史，MA200 狀態保留 null、不補未來值、不為此剔除主要分析。所有 entry-day 及未來 OHLCV 乘五的測試，仍得到相同 entry-time features。')
    rows=[]
    for r in d['heterogeneity']:
        if r['policy']=='conservative':
            s=r['delta_return_on_entry_cost_pp']
            rows.append([r['feature'],r['quantile'],r['candidate'],s['n'],num(s['mean']),num(s['median']),r['stock_count'],r['etf_count']])
    add('### 固定四分位描述（Conservative；非 cutoff 搜尋）')
    add(table(['特徵','Q（低→高）','候選','N','mean Δ pp','median Δ pp','個股 n','ETF n'],rows))
    add('四分位界線由 800 個唯一 anchors 的觀測特徵固定，一次套用所有候選／policy；它們只是事後描述，不是可部署的條件，也不能宣稱樣本外有效。完整 edges 與其他 policy 分組在 JSON heterogeneity。C 的 MA slope 四組 mean 為 0.165／0.216／0.642／0.177 pp；ATR% 為 0.070／0.642／0.128／0.362 pp。沒有「越強／越高就越有效」的單調證據。最低 ATR 組包含 100 個 ETF anchors、最高組沒有 ETF，也提醒組間成分混淆。')
    add('### 預先指定模型')
    add('OLS：delta entry-cost return ~ 六個指定特徵 + ticker fixed effects；每個係數按 within-ticker 一個標準差顯示。499 次兩向 cluster bootstrap 係數區間；另列 Huber IRLS point estimate，沒有 feature selection、調參或預測用途。ETF indicator 與 ticker FE 完全共線，不能另外識別；distance-MA20 在 Entry Zone v2 下近乎常數，不當作有效解釋變數。')
    rows=[]
    for k in ('B','C','D'):
        for name,v in d['models'][k]['conservative']['coefficients'].items():
            rows.append([k,name,num(v['ols_pp_per_sd']),interval(v['ci95']),num(v['huber_pp_per_sd'])])
    add(table(['候選','特徵','OLS pp/within-SD','95% 區間','Huber pp/SD'],rows))
    add('六個特徵在 B/C/D 的 Conservative 模型中均沒有區間穩定離開零；Huber 幾乎回到零，反映多數 entries 沒有效果與少數尾端對均值的重要性，並非沒有異質性的證明。全部 policy 的係數、樣本數、rank、condition number、有效 bootstrap 次數保存在 models。不要把任一正係數轉成新 strategy filter。')
    add('## 7. 50% → 25% → 0% 梯度')
    add(table(['Period','Policy','Return單調 symbols/11','Exposure單調/11','MDD逐步惡化/11','配對PnL單調/all','受影響交易中單調'],[[r['period'],POL[r['policy']],len(r['return_monotonic_symbols']),len(r['exposure_monotonic_symbols']),len(r['mdd_deterioration_monotonic_symbols']),f'{r.get("matched_monotonic","—")}/{r.get("matched_anchors","—")}',f'{r.get("changed_matched_monotonic","—")}/{r.get("changed_matched","—")}'] for r in d['gradients']]))
    add('曝險 50→25→0 在 99 組 symbol/period/policy 全部符合梯度；但報酬不是必然越少減碼越好。Conservative 只有受影響 113 筆中的 40 筆符合 Full≤D≤B 的 PnL 單調方向；其餘包含反向與非單調結果。D 的 MDD 成本通常較小，因此可以稱風險取捨更溫和，不能稱統計上已更穩健或最佳比例。')
    add('## 8. MA Break cross-sectional robustness')
    add(table(['候選','Policy','Return改善/11','Sharpe改善/11','ΔReturn median pp','ΔMDD median pp','ΔMDD p10 pp','ΔSharpe','ΔExposure pp','ΔTurnover'],[[k,POL[p],(r:=breadth(k,p))['return_better'],r['sharpe_better'],num(r['median']['return_pp']),num(r['median']['mdd_pp']),num(r['mdd_p10']),num(r['median']['sharpe']),num(r['median']['exposure_pp']),num(r['median']['turnover'])] for k in ('M1','M2','M3') for p in POL]))
    add('ΔMDD = candidate minus Full；正值是改善（回撤較不負）。M1 Conservative 中位數看似僅 -0.50 pp，但 p10 為 -24.44 pp；OHLC 推估／有利的中位數惡化 -7.59／-8.91 pp。移除完整 MA risk family 不能只看平均或中位 Return。')
    worst=sorted([r for r in d['portfolio'] if r['candidate']=='M1' and r['period']=='FULL' and r['policy']=='conservative'],key=lambda r:r['delta_vs_full']['mdd_pp'])[:4]
    add(table(['M1 回撤風險例','Return','MDD','ΔMDD pp','Peak','Trough','Recovery'],[[r['symbol'],pct(r['summary']['total_return']),pct(r['summary']['max_drawdown']),num(r['delta_vs_full']['mdd_pp']),r['summary']['max_drawdown_start'],r['summary']['max_drawdown_bottom'],r['summary']['recovery_date']] for r in worst]))
    add('### 跨期與 policy')
    add(table(['候選','Period','Policy','Return改善/11','Sharpe改善/11','ΔReturn pp','ΔMDD pp','ΔSharpe'],[[r['candidate'],r['period'],POL[r['policy']],r['return_better'],r['sharpe_better'],num(r['median']['return_pp']),num(r['median']['mdd_pp']),num(r['median']['sharpe'])] for r in d['breadth'] if r['candidate'].startswith('M') and r['period']!='FULL']))
    add(table(['候選','方向分類','兩子期間六cells正中位數','每個子期間×policy都同時提高Return/Sharpe的symbols'],[[r['candidate'],r['policy_label'],f'{r["subperiod_positive_cells"]}/6',', '.join(r['both_periods_all_policies_joint_symbols']) or '無'] for r in d['gate']['rows']]))
    add('ROBUST 在此描述的是 return/Sharpe 方向跨 policy／period，不表示風險或統計證據同樣 robust。POLICY-SENSITIVE 採較嚴的「任一子期間 median 符號跨 policy 改變」標籤；gate 另判斷是否極端敏感，因此 label 與 READY 不是同義。')
    add('## 9. MA matched-entry、局部反彈與後續下跌')
    add(table(['候選','Policy','ΔPnL $','mean Δreturn pp','changed-only median pp','有利/不利','Δholding calendar days mean','ΔMFE mean','ΔMAE mean','Δ滿倉等效days mean','terminal-censored'],[[k,POL[p],num((s:=stats(k,p))['concentration']['sum_delta_pnl'],2),num(s['bootstrap']['pooled_entry_point']['mean']),num(s['concentration']['changed_only']['median']),f'{s["concentration"]["changed_only"]["positive"]}/{s["concentration"]["changed_only"]["negative"]}',num(s['delta_outcomes']['delta_holding_days']['mean']),pct(s['delta_outcomes']['delta_mfe']['mean']),pct(s['delta_outcomes']['delta_mae']['mean']),num(s['delta_outcomes']['delta_exposure_days']['mean']),s['terminal_censored']] for k in ('M1','M2','M3') for p in POL]))
    add(f'NVDA M1 Conservative 延續上一輪 exact matched ΔPnL = ${num(stats("M1")["by_symbol"]["NVDA"]["pnl"]["sum"],2)}；77 筆逐筆核對通過。跨全部股票 M1 ${num(stats("M1")["concentration"]["sum_delta_pnl"],2)}，M3 ${num(stats("M3")["concentration"]["sum_delta_pnl"],2)}，M2 ${num(stats("M2")["concentration"]["sum_delta_pnl"],2)}。因此收益拖累不能主要歸於 BreakDayLow 全出場單一事件；半倉削減與整個 episode／政策互動更大。但 M1−M3 同時含半倉與追蹤／重置作用，不是嚴格的 additive causal decomposition。')
    add('M3 的 portfolio 改善比 matched-return 證據更強：換手顯著下降、entry與資金路徑改變，可能減少反覆出入的損失；其 matched mean 區間跨零，移除每股最大 delta 後 mean 也略負。因此不得把 portfolio MDD 改善直接當 BreakDayLow 出場普遍錯誤的證明。')
    add('### 實際 Full MA events 之後的 underlying forward return')
    add('從該次實際 sell execution price（已含滑價）計算未來第 5/10/20/40 個交易日 close return，不再扣持有成本或交易佣金；不是 counterfactual strategy PnL。Recovery frequency 定義為「該 horizon close > event fill」，不是途中曾回升，也不是回到原始 entry。Unavailable endpoint 不當零，分母逐 horizon 顯示；事件可在同一 ticker/position 聚集，僅描述。')
    rows=[]
    for r in d['forward_summary']:
        if r['group']!='all':continue
        for n,v in r['horizons'].items():rows.append([POL[r['policy']],r['event'],n,v['n'],pct(v['mean']),pct(v['median']),pct(v['recovery_frequency']),pct(v['continued_decline_frequency'])])
    add(table(['Policy','Event','D','可用 n','mean','median','close恢復率','close仍下跌率'],rows))
    add('Conservative：half-stop 的 20D median +2.68%、40D +2.33%；BreakDayLow 的 20D +2.64%、40D +4.70%。反彈較常見，但 half-stop 的 40D 仍約 43% 持續低於賣價，BreakDayLow 約 39%。兩者都切到噪音與真跌破，不能僅用正 median 判定應移除所有風控；M1 回撤尾部正是風險仍存在的反證。')
    add('## 10. Evidence matrix 與 Walk-forward gate')
    add('先檢查可行性與風險門檻，再在合格 MA 候選中考慮證據等級／廣度；不讓報酬較高但回撤失敗的 M1 擠掉通過必要 screens 的 M3。原始數值、分類、全部通過/失敗理由均保存在 gate。')
    add(table(['Screen','固定定義'],[[k,v] for k,v in d['design']['gate'].items()]))
    rows=[]
    for k in d['gate']['matrix_candidates']:
        if k=='A':rows.append(['A','REFERENCE','基準','基準','基準','基準','基準','基準','不適用','保留 production']);continue
        r=next(x for x in d['gate']['rows'] if x['candidate']==k); s=r['screens']; yes=lambda k:'通過' if s[k] else '未通過'
        rows.append([k,r['grade'],yes('majority'),yes('period'),yes('policy'),yes('drawdown'),yes('matched'),yes('concentration'),yes('uncertainty'),'READY FOR WALK-FORWARD' if r['walk_forward_eligible'] else 'NOT READY'])
    add(table(['候選','等級','Return/Sharpe廣度','跨期','Policy','MDD','Matched移除集中股票','贏家集中度','均值區間','決定'],rows))
    add(table(['候選','曝險／換手（Conservative medians）','複雜度與依賴'],[[k,f'Δexposure {num(breadth(k)["median"]["exposure_pp"])} pp；Δturnover {num(breadth(k)["median"]["turnover"])}',('原 downstream 邏輯、少一個 immediate sale' if k=='B' else '少兩個 Extreme partial 分支／edge銷售用途' if k=='C' else '原模組、一個固定25% checkpoint' if k=='D' else '保留 episode tracking/reset，少一個 full-exit 分支')] for k in ('B','C','D','M3')]))
    add('E 補充：同樣通過六個探索性 screen，MODERATE，非 STRONG；其改進小且集中、均值區間跨零。因本輪指定主矩陣不含 E，本報告不把它取代 D 或新增為主矩陣候選；最多推薦一個 M3。M1 在配對收益上的證據比 M3 強，但明確未通過 MDD gate，不可作 production 或 walk-forward 推薦。')
    add('M3 下一步僅值得「先鎖定語意、資料隔離與評估指標後的 prospective walk-forward 驗證」；本輪沒有執行它，也沒有宣稱樣本外成功。Gate 的 -3 pp median/-10 pp p10 是研究者事前設定的風險 screen，不是使用者已承諾可接受的真實損失。')
    add('## 11. 配對交易明細與可重現性')
    add('完整 machine-readable：[pre-v3-evidence-gate.json](../data/pre-v3-evidence-gate.json)；獨立配對表：[pre-v3-matched-entries.json](../data/pre-v3-matched-entries.json)。配對表使用 columns + rows，避免 16,800 行重複 key 與 feature；以 symbol/position_id join anchors_with_features，policy/candidate 組成唯一 row key。無需重算正式 backtest 或修改 audits。')
    add('重現：在專案根目錄使用既有 backend Python 執行 `python -B -m research.run_evidence`；僅讀 frozen caches/DB，計算後以 stdout 串流輸出 report/table（輸入 `report 0`、`table 0` 等 chunk index；`done` 離開）。不呼叫資料 provider、不寫 production persistence。固定 bootstrap seed，數值重現；runtime 不作一致性比較。')
    for k in ('C','M1','M3'):
        add(f'### {k}：Conservative 最大改善／損害各 10 筆')
        c=stats(k)['concentration']
        add(table(['symbol/position','Entry','Full PnL $','Candidate PnL $','ΔPnL $','Δreturn pp','Full exit','Candidate exit','Candidate reason','Δholding'],[[r['symbol']+'/'+r['position_id'],r['entry_date'],num(r['full_net_pnl'],2),num(r['candidate_net_pnl'],2),num(r['delta_net_pnl'],2),num(r['delta_return_on_entry_cost_pp']),r['full_exit_date'],r['candidate_exit_date'],r['candidate_reason'],r['delta_holding_days']] for r in c['top_positive']+c['top_negative']]))
    add('## 12. Limitations')
    add('- 所有股票是事後指定且高度偏大型科技／成長股；SPY/QQQ 不是獨立市場，存在成分重疊與 survivorship/selection bias。結論不能外推全市場。\n- Fixed entry 研究不能作可交易多部位 portfolio：不同 anchor 反事實可能互相重疊，美元加總受資金與 Q0 路徑影響；用 normalized return 與 ticker/episode clusters 降低但不消除此問題。\n- Full-period/subperiod/三個 policy 共用同一條歷史資料；不增加獨立樣本數，不宣稱樣本外。\n- Genuine daily path 不可識別，三種 policy 都是假設；本輪一律沿用已凍結實作，不修 execution semantics。\n- Bootstrap 只有少量 clusters，block邊界、重尾、zero-inflation、policy/episode overlap 均限制 coverage；沒有多重檢定調整的 confirmatory significance claims。\n- 剪尾不是策略，不刪除已保存交易；Top-N 選取為事後描述，不能把選到的交易當可提前辨識訊號。\n- MFE/MAE、forward returns、贏家身分僅是事後 outcome，不輸入 entry diagnostics；MA200 缺值不向後填補。\n- 結束日仍持有的反事實有 terminal censoring；JSON 對每個候選/policy保存排除 endpoint 的敏感度。它不是額外自然出場。\n- Turnover 是雙邊 gross traded notional / 平均每日 equity；exposure 是每日收盤股票市值/equity平均，不是單純持有時間。\n- 沒有新增資料供應商或更換調整基準。所有數字仍受既有 Yahoo adjusted-price reporting 口徑影響。')
    add(table(['候選','Policy','終點截斷筆數','排除後 n','排除後 mean Δreturn pp'],[[k,POL[p],(s:=stats(k,p))['terminal_censored'],s['uncensored_sensitivity']['n'],num(s['uncensored_sensitivity']['mean'])] for k in ('B','C','D','E','M1','M2','M3') for p in POL]))
    add('## 13. 不變性與驗證')
    add(f'Canonical Simple/Advanced 由正式 engine in-memory replay；99 個 Full symbol/period/policy portfolio 與前輪完全相同；2400 個 Candidate C matched lifecycle 的 executions hashes／PnL 與前輪完全相同；77 個 NVDA no-MA matched deltas 與 ablation 完全相同。研究計算耗時約 {d["runtime_seconds"]:.1f} 秒（不含文件／測試／建置）。')
    add(table(['保護目標','修正前/後 hash 相同','SHA256'],[[k,'是',v] for k,v in d['immutability']['before'].items()]))
    add('Database fingerprint 涵蓋所有 backtests 與 position_audits rows。production source fingerprint 涵蓋 backend/app 全部 Python；既有 research/report/data JSON hash 也逐一檢查。Executions、quantities、prices、net PnL、equity、metrics 變更數 = 0。最終測試／build 紀錄另保存在 [pre-v3-validation.json](../data/pre-v3-validation.json)。沒有 Browser Use。')
    add('## Appendix A. First TP 全期間逐股票×policy')
    add(table(['symbol','policy','候選','Return','CAGR','MDD','Sharpe','Exposure','Positions','Turnover','ΔReturn pp','ΔMDD pp'],[[r['symbol'],POL[r['policy']],r['candidate'],pct(r['summary']['total_return']),pct(r['summary']['cagr']),pct(r['summary']['max_drawdown']),num(r['summary']['sharpe_ratio']),num(r['exposure']['average_close_capital_exposure_pct']),r['summary']['number_of_positions'],num(r['exposure']['two_sided_turnover']),num(r['delta_vs_full']['return_pp']),num(r['delta_vs_full']['mdd_pp'])] for r in d['portfolio'] if r['period']=='FULL' and r['candidate'] in 'ABCDE']))
    add('## Appendix B. MA family 全部 symbol×period×policy')
    add('A 列為 unchanged Full；含 11×3×3×4 = 396 列。全部 drawdown episodes（peak/trough/recovery）、costs、其他績效欄位保存在 JSON portfolio。')
    add(table(['symbol','period','policy','候選','Return','CAGR','MDD','Sharpe','Exposure','Positions','Turnover','ΔReturn pp','ΔMDD pp','ΔSharpe'],[[r['symbol'],r['period'],POL[r['policy']],r['candidate'],pct(r['summary']['total_return']),pct(r['summary']['cagr']),pct(r['summary']['max_drawdown']),num(r['summary']['sharpe_ratio']),num(r['exposure']['average_close_capital_exposure_pct']),r['summary']['number_of_positions'],num(r['exposure']['two_sided_turnover']),num(r['delta_vs_full']['return_pp']),num(r['delta_vs_full']['mdd_pp']),num(r['delta_vs_full']['sharpe'])] for r in d['portfolio'] if r['candidate'] in ('A','M1','M2','M3')]))
    return '\n'.join(lines).rstrip()+'\n'

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(render(json.loads((ROOT/'data/pre-v3-evidence-gate.json').read_text(encoding='utf-8'))),end='')
