"""Render the frozen structural result as a Traditional Chinese research report."""
import json
import math
import statistics
import sys
from research import ROOT

POLICY={"conservative":"保守", "ohlc_heuristic":"OHLC 推估", "favorable":"有利"}
NAME={"A":"Full 50%＋Extreme", "B":"Signal only；保留 Extreme", "C":"Signal＋Protective；無獲利減碼", "D":"首次減碼 25%", "E":"50%＋Protective；無 Extreme"}


def n(x,digits=2):
    return "—" if x is None else f"{x:,.{digits}f}"


def pct(x):
    return "—" if x is None else n(x*100)+"%"


def table(headers,rows):
    return "\n".join(["| "+" | ".join(headers)+" |","| "+" | ".join("---" for _ in headers)+" |"]+
                     ["| "+" | ".join(str(x).replace("|","/").replace("\n"," ") for x in row)+" |" for row in rows])


def render(d,validation=None):
    lines=[]
    def add(x=""):
        lines.append(x)
    def section(title):
        add("\n## "+title+"\n")
    def tbl(headers,rows):
        add(table(headers,rows));add()
    def portfolio(symbol=None,period="FULL",policy=None,key=None):
        return [r for r in d["portfolio"] if (symbol is None or r["symbol"]==symbol) and r["period"]==period
                and (policy is None or r["policy"]==policy) and (key is None or r["candidate"]==key)]
    def br(period,policy,key):
        return next(r for r in d["breadth"] if (r["period"],r["policy"],r["candidate"])==(period,policy,key))
    def breadth_table(rows):
        tbl(["期間","Policy","候選","R↑/↓/=","Sharpe↑/↓/=","MDD 改善/惡化/=","ΔReturn 中位 pp","ΔMDD 中位 pp","ΔSharpe 中位"],
            [[r["period"],POLICY[r["policy"]],r["candidate"],f'{r["return_better"]}/{r["return_worse"]}/{r["return_tied"]}',
              f'{r["sharpe_better"]}/{r["sharpe_worse"]}/{r["sharpe_tied"]}',f'{r["mdd_better"]}/{r["mdd_worse"]}/{r["mdd_tied"]}',
              n(r["distributions"]["return_pp"]["median"]),n(r["distributions"]["mdd_pp"]["median"]),n(r["distributions"]["sharpe"]["median"],3)] for r in rows])
    add("# First TP Structural Robustness — Advanced Strategy v2\n")
    add("研究日期：2026-09-04。Research-only；沒有參數搜尋、沒有新增正式策略、沒有改動 production 或歷史資料。")
    add("\n完整逐項數值、2,400 筆 C 配對記錄、2,400 筆固定期限記錄與資料雜湊：[machine-readable JSON](../data/first-tp-structural-robustness.json)。資料凍結清單：[inputs](../data/first-tp-structural-inputs.json)。")
    section("1. Executive Summary")
    add("取消獲利減碼有跨股票的正向證據，但 **不能把 NVDA 的大幅改善推廣為普遍有效的 v3**。完整五年中，B/C/D/E 在三種 policy 的報酬與 Sharpe 跨標的中位增量均為正；子期間卻有負向／方向反轉，多數標的 MDD 加深。依事前固定的嚴格判準，四者皆為 **POLICY-SENSITIVE／Promising but needs validation**，沒有 Strong candidate。此標籤包含子期間中位數接近零而翻號的情況，不表示五年改善方向全部翻轉。\n")
    tbl(["候選","保守模式報酬改善標的","ΔReturn 中位 pp","ΔMDD 中位 pp","ΔSharpe 中位","三 policy 同時 Return＋Sharpe 改善"],
        [[k,f'{br("FULL","conservative",k)["return_better"]}/11',n(br("FULL","conservative",k)["distributions"]["return_pp"]["median"]),
          n(br("FULL","conservative",k)["distributions"]["mdd_pp"]["median"]),n(br("FULL","conservative",k)["distributions"]["sharpe"]["median"],3),
          f'{len(next(r for r in d["robustness"] if r["candidate"]==k)["all_three_policies_joint_improved_symbols"])}/11'] for k in "BCDE"])
    add("C 在 NVDA 的保守模式增量是 +161.67 pp，但跨 11 標的中位數只有 +4.89 pp。C 的 SPY／QQQ 報酬與 Sharpe 在三種 policy 下均惡化；MSFT 報酬也都惡化。更高曝險並不保證更多 alpha。C 保守模式只有 3/11 標的絕對報酬為正，不能把『虧得比較少』說成可部署的盈利策略。\n")
    ps=d["protective_fixed_horizon"]["summary"]["conservative"]["pooled"]
    add(f'Protective 的 40 日配對：800 個固定進場中，{ps["complete_horizon_anchors"]} 個期限完整，{ps["endpoint_censored_excluded"]} 個尾端不足樣本排除。Protective 對無 Protective 之虧損組減少損失 ${n(ps["loss_avoided_vs_off_losers"])}，對其獲利組犧牲 ${n(ps["upside_sacrificed_vs_off_winners"])}；合計配對差額 ${n(ps["sum_delta_on_minus_off"])}。它確有 downside protection，但不是免費午餐；這些不是 portfolio PnL。')
    section("2. Candidate definitions / 凍結研究設計")
    tbl(["代號","名稱","首次 +3% 訊號","立即減碼 current qty","Protective","Bias/ATR 減碼"],
        [[k,v["name"],"保留",pct(v["first_tp_current_quantity_fraction"]),"保留","保留" if v["modules"]["bias"] else "停用"] for k,v in d["candidate_definitions"].items()])
    add("所有候選保留正式 Entry Zone v2（Open > UpperEntry 不追價）、量能確認、第二日確認、MA 半倉停損／Break Protection，以及正式優先順序。首次訊號後不把 MA 半倉風控偷偷重新啟用。C 的保留 Protective 仍為 max(P0, MA(t−1) × 0.985)，同日新啟用停損的處理完全沿用既有 policy。")
    add("\nD 只測一次 25% checkpoint：`max(1, current_qty // 4)`；A/E 為 `max(1, current_qty // 2)`。維持原有 whole-share 最少 1 股規則、<20% Q0 禁止獲利分批賣出；MA half-stop 仍是 current // 2，不受 D 影響。B/C 無立即賣出，但 FIRST_TP_TRIGGERED 狀態仍正常切換。")
    req=d["canonical"]["advanced"]["request"]
    add("\n共同 request（所有標的／期間／policy 僅改代號、日期或 policy；candidate 開關留在研究層）：\n")
    add("```json\n"+json.dumps({k:v for k,v in req.items() if k not in ("ticker","start_date","end_date","execution_policy")},ensure_ascii=False,indent=2)+"\n```")
    add("\nMA/ATR 僅使用 t−1；sigma 僅使用已完成歷史。唯 Break Reset 用收盤後 MA(t)。同一 candidate 無任何跨股票或跨期間調參。全期間與 A/B 子期間各自從 $100,000 空倉重置，不承接前段部位／資金；暖機資料仍在開始日前。")
    section("3. NVDA canonical verification")
    for key,v in d["canonical"].items():
        add(f'- {key}: `{v["backtest_id"]}`；完整結果 SHA-256 `{v["result_sha256"]}`。')
    add("\n正式 engine 的 canonical Simple／Advanced executions、net PnL、equity 與所有 metrics 均零差異。先前研究 A/B/C/E 的保守模式成交／equity hash／完整績效精確相同；Full 的三種 policy 也與先前 ambiguity 報告精確相同。D 是唯一新比例 checkpoint。\n")
    nv=portfolio("NVDA")
    tbl(["Policy","候選","Return","CAGR","MDD","Sharpe","PF","勝率","平均交易","中位交易","Positions"],
        [[POLICY[r["policy"]],r["candidate"],pct(r["summary"]["total_return"]),pct(r["summary"]["cagr"]),pct(r["summary"]["max_drawdown"]),
          n(r["summary"]["sharpe_ratio"],3),n(r["summary"]["profit_factor"]),pct(r["summary"]["win_rate"]),pct(r["summary"]["average_trade_return"]),
          pct(r["summary"]["median_trade_return"]),r["summary"]["number_of_positions"]] for r in nv])
    tbl(["Policy","候選","平均收盤曝險 %","平均持有日","雙邊 turnover","手續費 $","滑價 $"],
        [[POLICY[r["policy"]],r["candidate"],n(r["exposure"]["average_close_capital_exposure_pct"]),n(r["summary"]["average_holding_days"]),
          n(r["exposure"]["two_sided_turnover"]),n(r["summary"]["total_commission"]),n(r["summary"]["estimated_slippage_cost"])] for r in nv])
    section("4. Cross-symbol results / Data provenance")
    add(f'所有 11 標的的共同策略區間為 {d["common_start"]} ～ {d["common_end"]}。每檔 1,442 根含暖機日線／1,255 根區間內日線／187 根暖機。逐日 session dates 完全一致，沒有縮短期間或默默填補缺日。無標的因 adjustment 不一致被納入或排除；所有來源均為 Yahoo。未獨立核對交易所完整日曆，跨標的一致不等於能排除來源共有缺日。\n')
    tbl(["Symbol","Provider","Metadata adjustment label","First / Last","Bars","快取更新時間"],
        [[r["symbol"],r["provider"],r["adjustment_mode"],r["first_date"]+" / "+r["last_date"],r["bars"],r["cache_metadata"][0]["last_updated"]] for r in d["data_manifest"]["symbols"]])
    add("正式 Yahoo 程式的實際口徑：以 adjusted_close / close 比例調整 Open/High/Low/Close，volume 原樣保留；因此不只是拆股，還可能包含 Yahoo 的股利調整。`adjusted_for_splits` 是既有不精確標籤，本輪只揭露、不修 production metadata。沒有另加股利現金流。既有 NVDA/AAPL/SPY cache 與本輪新資料沿用相同 Yahoo contract；逐檔內容／檔案 hash 已凍結。沒有重新抓取或改寫 canonical NVDA，來源之調整修訂風險與非 point-in-time 限制仍存在。Stooq native-adjusted 不能證明等價，研究 acquisition 會排除而非混合。\n")
    for policy in POLICY:
        add("### "+POLICY[policy]+"：完整期間\n")
        tbl(["Symbol","候選","Return","CAGR","MDD","Sharpe","曝險 %","Positions","ΔR pp","ΔMDD pp","ΔSharpe","Δ曝險 pp"],
            [[r["symbol"],r["candidate"],pct(r["summary"]["total_return"]),pct(r["summary"]["cagr"]),pct(r["summary"]["max_drawdown"]),
              n(r["summary"]["sharpe_ratio"],3),n(r["exposure"]["average_close_capital_exposure_pct"]),r["summary"]["number_of_positions"],
              n(r["delta_vs_full"]["return_pp"]),n(r["delta_vs_full"]["mdd_pp"]),n(r["delta_vs_full"]["sharpe"],3),n(r["delta_vs_full"]["exposure_pp"])] for r in portfolio(policy=policy)])
    add("Δ 都是 candidate − 同 symbol／期間／policy Full。MDD 以負報酬表示，因此 ΔMDD > 0 表示改善，<0 表示更深。零附近判定 tolerance 1e−9。下表分母均 11，不用大贏家拉動的平均報酬取代廣度：\n")
    breadth_table([r for r in d["breadth"] if r["period"]=="FULL"])
    add("剔除 NVDA 後仍為正，但改善量明顯較小：\n")
    tbl(["Policy","候選","N","報酬改善","ΔReturn 中位 pp","ΔSharpe 中位"],
        [[POLICY[r["policy"]],r["candidate"],r["symbols"],r["return_better"],n(r["distributions"]["return_pp"]["median"]),n(r["distributions"]["sharpe"]["median"],3)] for r in d["breadth_excluding_nvda"] if r["period"]=="FULL"])
    section("5. Cross-period results / regime explanation")
    add("Period A：2021-09-01～2023-12-31（最後交易日 2023-12-29）；Period B：2024-01-01～2026-09-01（第一交易日 2024-01-02）。11 檔兩段皆 available，所有候選共用同一段暖機／交易日。這兩段不是純粹的 bear／bull 標籤，不使用它們宣稱已識別因果 regime。\n")
    breadth_table([r for r in d["breadth"] if r["period"]!="FULL"])
    add("C 保守模式在兩段中位增量都正（+4.66／+2.92 pp），不能說『只在 2024 年後牛市有效』；但推估模式 Period A 為 −0.64 pp，有利模式 Period B 為 −0.08 pp／Sharpe −0.025，因此也不能說跨 regime 已一致成立。各股票有相反案例：AAPL 在 A 改善、B 惡化；GOOGL A 惡化、B 改善；AVGO 的 B 即使買入持有大漲，C 仍差於 Full。\n")
    tbl(["Symbol","A Buy&Hold","A Full","A C","A ΔR pp","B Buy&Hold","B Full","B C","B ΔR pp"],
        [[s]+[value for per in ("A","B") for r in portfolio(s,per,"conservative","C") for value in
              [pct(r["summary"]["buy_hold_return"]),pct(portfolio(s,per,"conservative","A")[0]["summary"]["total_return"]),pct(r["summary"]["total_return"]),n(r["delta_vs_full"]["return_pp"])]]
         for s in [r["symbol"] for r in d["data_manifest"]["symbols"] if r["status"]=="included"]])
    add("### 所有子期間 symbol × candidate × policy\n")
    for per in ("A","B"):
        for policy in POLICY:
            add(f'#### Period {per} — {POLICY[policy]}\n')
            tbl(["Symbol","候選","Return","CAGR","MDD","Sharpe","曝險 %","Positions","ΔR pp","ΔMDD pp","ΔSharpe","Δ曝險 pp"],
                [[r["symbol"],r["candidate"],pct(r["summary"]["total_return"]),pct(r["summary"]["cagr"]),pct(r["summary"]["max_drawdown"]),
                  n(r["summary"]["sharpe_ratio"],3),n(r["exposure"]["average_close_capital_exposure_pct"]),r["summary"]["number_of_positions"],
                  n(r["delta_vs_full"]["return_pp"]),n(r["delta_vs_full"]["mdd_pp"]),n(r["delta_vs_full"]["sharpe"],3),n(r["delta_vs_full"]["exposure_pp"])] for r in portfolio(period=per,policy=policy)])
    section("6. Intrabar-policy robustness")
    add("沿用現行 Conservative／OHLC Heuristic／Favorable，不重新定義 Conservative。它們不是實際 tick paths，也不是數學上的全域最差／最佳界限。先前 ambiguity 研究已說明：部分新啟用 Protective 分支共用保守處理、Favorable entry resolver 不檢查所有 Close 可確定的次序。因此『robust』僅指對現行三個實作的敏感度，不能聲稱已涵蓋所有 OHLC 可行路徑。\n")
    add("判準在研究程式中事先凍結，非按本輪結果挑 cutoff：ROBUST 需三 policy 五年中位 ΔReturn、ΔSharpe >0、至少 ceil(2N/3)=8 檔在三 policy 同時改善兩指標，且兩子期間各 policy 中位兩指標也都正。任一期間中位 ΔReturn 或 ΔSharpe 跨 policy 翻號，或 joint breadth 跨 policy 相差 ≥ceil(N/3)，標 POLICY-SENSITIVE；否則 MIXED。此為描述性分類，不是顯著性檢定。\n")
    tbl(["候選","分類","五年三 policy 都改善 Return＋Sharpe 的 symbols","A/B 兩段、三 policy 都改善兩指標"],
        [[r["candidate"],r["label"],", ".join(r.get("all_three_policies_joint_improved_symbols",[])) or "—",", ".join(r.get("both_subperiods_all_policies_joint_improved_symbols",[])) or "—"] for r in d["robustness"]])
    section("7. Exposure analysis / 25% gradient")
    add("Exposure = 全期間每個收盤 stock market value / equity 的平均；不是單純『持倉天數比例』。強制期末清倉後最後一天為 0；同日進出不占收盤曝險。time-in-market、平均持股、cash、成交總額皆另存 JSON。turnover = 買賣總成交額 / 平均 daily equity（雙邊，非單邊）；持有日為 calendar days。\n")
    tbl(["Policy","候選","Δ平均曝險中位 pp","Δturnover 中位","ΔReturn 中位 pp","ΔMDD 中位 pp"],
        [[POLICY[r["policy"]],r["candidate"],n(r["distributions"]["exposure_pp"]["median"]),n(r["distributions"]["turnover"]["median"]),n(r["distributions"]["return_pp"]["median"]),n(r["distributions"]["mdd_pp"]["median"])] for r in d["breadth"] if r["period"]=="FULL"])
    tbl(["期間","Policy","N","Return A ≤ D ≤ B","Exposure A ≤ D ≤ B"],
        [[r["period"],POLICY[r["policy"]],r["symbols"],len(r["return_A_le_D_le_B"]),len(r["exposure_A_le_D_le_B"])] for r in d["exposure_gradient"]])
    add("50%→25%→0% 的曝險梯度在 11 檔、兩子期與全期、三 policy 共 99 個情境都成立；報酬卻非全部單調。完整期 return 梯度只有 8/11、7/11、7/11（保守／推估／有利）。所以 25% 支持『減碼改變 winner exposure』這個機制，但不是 25% 最優、或每次減碼都是錯的證據。較少 partial orders 也不保證 dollar turnover／總手續費下降：更大本金與更高 equity 會改變後續下單。NVDA C 的 turnover 反而高於 Full；這是資金路徑，不是新規則。")
    section("8. Winner retention / Top 10 benefited")
    add(d["matched_candidate_c"]["anchor_design"]+"\n")
    add("800 筆各股票 Full Conservative entry 固定 P0、Q0；三 policy 各自配對 A vs C。下列為保守模式 dollar delta 排序，不是可投入同一資本的合成 portfolio。跨股票 Q0 來自各自 canonical-style Full 的資金路徑，故另附以 entry execution notional 正規化的平均增量。\n")
    ms=d["matched_candidate_c"]["summary"]["conservative"]
    tbl(["Symbol","Anchors","受益/受損/不變","ΣC−Full $","Full winner Δ$","Full loser Δ$","平均 Δ/進場額 pp","多保留 Q0-session"],
        [[s,r["anchors"],f'{r["benefited"]}/{r["harmed"]}/{r["anchors"]-r["changed"]}',n(r["sum_delta_pnl"]),n(r["winner_delta"]),n(r["loser_delta"]),n(r["delta_return_on_entry_notional_pp"]["mean"],3),n(r["extra_q0_sessions"])] for s,r in ms["by_symbol"].items()])
    def top_table(rows):
        tbl(["Symbol / Position","Entry","Full PnL $","C PnL $","Δ$","Δ/進場額 pp","Full exit / C exit","原因 Full / C","持有日 Full / C","Δ持有日","額外 Q0-session"],
            [[r["symbol"]+" "+r["position_id"],r["entry_date"][:10],n(r["full"]["net_pnl"]),n(r["candidate_c"]["net_pnl"]),n(r["delta_pnl"]),n(r["delta_return_on_entry_notional_pp"]),
              r["full"]["final_exit_date"][:10]+" / "+r["candidate_c"]["final_exit_date"][:10],r["full"]["exit_final_close_reason"]+" / "+r["candidate_c"]["exit_final_close_reason"],
              str(r["full"]["holding_days"])+" / "+str(r["candidate_c"]["holding_days"]),r["holding_days_delta"],n(r["extra_q0_sessions"])] for r in rows])
    top_table(ms["pooled"]["top_benefited"])
    total=ms["pooled"]["sum_delta_pnl"]; nvda=ms["by_symbol"]["NVDA"]["sum_delta_pnl"]
    add(f'保守模式 800 筆中，只有 {ms["pooled"]["changed"]} 筆 PnL 改變：{ms["pooled"]["benefited"]} 受益、{ms["pooled"]["harmed"]} 受損，全部配對的 median Δ=0；少數大贏家抵銷更多的小幅回吐。ΣΔ=${n(total)}，NVDA 占淨差額 {pct(nvda/total)}。這不是『大部分交易都變好』。所有保守模式配對的 exit date／持有日皆不變：本次差距主要是同一持有期間股票數較多，不是新的進出場時機。\n')
    add("Q0-session = Σ daily close quantity / Q0；『多 10』代表多保留相當於原始滿倉 10 個交易日，並非 calendar 持有日增加。完整逐日 trajectories 見 JSON；以下列進出／數量變動日，省略數量未變日（未 forward-fill 新 threshold）：\n")
    for t in d["matched_candidate_c"]["top_position_quantity_trajectories"]:
        if (t["symbol"],t["position_id"]) not in [("NVDA","position-31"),("GOOGL","position-62"),("AVGO","position-26"),("META","position-72")]:
            continue
        add(f'### {t["symbol"]} {t["position_id"]} — Q0={t["q0"]}\n')
        selected=[];last=None
        for i,r in enumerate(t["daily"]):
            qs=(r["full_qty"],r["candidate_c_qty"])
            if qs!=last or i==len(t["daily"])-1:
                reasons=lambda es:", ".join(e["reason"] for e in es if e["timestamp"][:10]==r["date"]) or "—"
                selected.append([r["date"],n(r["close"]),r["full_qty"],r["candidate_c_qty"],pct(r["full_qty"]/t["q0"]),pct(r["candidate_c_qty"]/t["q0"]),reasons(t["full_executions"]),reasons(t["candidate_c_executions"])])
            last=qs
        tbl(["Date","Close $","Full qty","C qty","Full/Q0","C/Q0","Full event","C event"],selected)
    section("9. Loss protection / Top 10 harmed")
    top_table(ms["pooled"]["top_harmed"])
    add("明確反例：META position-72 曾剛碰 +3% 後遇反轉／gap，兩者皆 Protective 出場，但 C 保留較多股，淨損由 −$1,694.15 擴大至 −$7,719.35；breakeven floor 是 stop trigger，不保證跳空可在 P0 成交。AVGO position-57 則是較早高價減碼原本保住了部分利潤，取消減碼反而少賺 $5,346.20。不能因幾個 major winners 就忽略這些 insurance-like partial benefits。\n")
    add(f'按 Full 的最終輸贏分組，保守模式 C 對 Full winners 增加 ${n(ms["pooled"]["winner_delta"])}，對 Full losers 增加損失 ${n(-ms["pooled"]["loser_delta"])}。這是事後分組的機制描述；不是能事前辨識 winner／loser 的訊號。候選 C 仍有完整原風控與 Protective，但「仍有風控」不等於 downside 已充分受控。\n')
    add("### Full vs C 主要 drawdown episodes（保守）\n")
    tbl(["Symbol","候選","MDD","Peak","Trough","Recovery"],
        [[r["symbol"],r["candidate"],pct(r["summary"]["max_drawdown"]),r["summary"]["max_drawdown_start"],r["summary"]["max_drawdown_bottom"],r["summary"]["recovery_date"] or "未恢復"]
         for r in portfolio(policy="conservative") if r["candidate"] in "AC"])
    add("每個候選所有 policy／期間的最差三個 DD episodes 都保存在 JSON。比較 ΔMDD 是比較各自 equity curve 的最差 episode，並非把同一市場事件的損益直接相減。完整期 C 的 MDD 改善僅 3/11、1/11、1/11（保守／推估／有利）；大多數標的用較深回撤換較高持股。")
    section("10. Protective Stop fixed-horizon study")
    add("評估 C（無 profit partial、有 Protective）對照無 profit partial／無 Protective。進場日為 day 0，觀察到第 40 個後續交易日收盤；各邊先自然出場者保持現金，不再進場。存活至期限則按該日 Close 套同樣 slippage／commission 全出。沒有 40 個完整後續 session 的 31 個 entry 從主要統計排除，即使其中自然出場很早，也不因結果挑樣本。沒有拿延伸至五年資料末端的部位當投組績效。\n")
    add("No Protective 的 research control 保留 entry、Volume、Day2、MA Break（signal 前）；signal 後不復活舊 MA half-stop，也不引入任何新止損。這是有意移除 post-signal protection 的有限期限對照，不是建議交易版本。固定 40 是預先選定的共同評估窗口，沒有搜尋其他 horizon。單筆損失／MDD 使用 entry notional 正規化、含費用的 daily-close marked account；不是盤中最大損失。\n")
    tbl(["Policy","完整/排除","改變","受益/受損","Protective ΣΔ$","off losers 避免損失 $","off winners 犧牲上檔 $","平均 Δ/進場額 pp","平均單筆 MDD 改善 pp"],
        [[POLICY[p],f'{v["pooled"]["complete_horizon_anchors"]}/{v["pooled"]["endpoint_censored_excluded"]}',v["pooled"]["changed_lifecycles"],
          f'{v["pooled"]["benefited"]}/{v["pooled"]["harmed"]}',n(v["pooled"]["sum_delta_on_minus_off"]),n(v["pooled"]["loss_avoided_vs_off_losers"]),
          n(v["pooled"]["upside_sacrificed_vs_off_winners"]),n(v["pooled"]["normalized_return_delta_pp"]["mean"],3),n(v["pooled"]["mdd_improvement_pp"]["mean"],3)] for p,v in d["protective_fixed_horizon"]["summary"].items()])
    add("上述 ΣΔ 為 independent anchored positions 的美元總和，可能時間重疊且股數不同，不能除以 $100,000 當報酬率。769 筆原始 entry 不會因三 policy 被算成 2,307 筆獨立證據。所有 policy 的整體 median Δ 與 median MDD improvement 都是 0（大多數交易在 regime transition 前結束）。只看有改變的部位，median Δ 為負，表示 downside control 有明確 upside premium。\n")
    tbl(["Symbol","完整 N","改變","受益/受損","ΣProtective on−off $","避免虧損 $","犧牲上檔 $","平均單筆 Δ/進場額 pp","平均單筆 MDD 改善 pp"],
        [[s,r["complete_horizon_anchors"],r["changed_lifecycles"],f'{r["benefited"]}/{r["harmed"]}',n(r["sum_delta_on_minus_off"]),n(r["loss_avoided_vs_off_losers"]),n(r["upside_sacrificed_vs_off_winners"]),
          n(r["normalized_return_delta_pp"]["mean"],3),n(r["mdd_improvement_pp"]["mean"],3)] for s,r in d["protective_fixed_horizon"]["summary"]["conservative"]["by_symbol"].items()])
    add("保守模式 Protective 的淨配對增值在 AAPL／AMZN／META／MSFT 四檔為正；11 檔平均單筆 MDD 改善都 >0。NVDA 74 個完整 40-session entry：避免 $79,284.52 的 off-loser 損失、犧牲 $84,901.90 的 off-winner 上檔，淨 −$5,617.39；平均單筆 MDD 改善 2.09 pp。這支持『Protective 是有成本的 downside protection』，不支持『移除 Protective 會普遍更好』或『保留它就足夠安全』。\n")
    add(f'期限行政清倉數（保守）：on {ps["on_horizon_liquidations"]}、off {ps["off_horizon_liquidations"]}。與 endpoint censoring 不同，這是兩組共享且預先固定的 horizon，但結論仍僅限 40 日，不外推長期收益。')
    section("11. Candidate ranking / 多維比較")
    add("不按 NVDA 或平均最高報酬排一條名次。Strong 要同時達上述 ROBUST、至少 8 個可比標的、各 policy 中位 MDD 惡化不超過 5 pp。Promising 要至少兩 policy 中位報酬／Sharpe 改善、且每 policy 至少一半標的報酬改善。這只是 evidence screen；曝險、turnover、複雜度與子期反例必須一同讀。\n")
    tbl(["候選","分類","Policy tag","五年 joint 全 policy N","雙子期 joint 全 policy N","保守 ΔR 中位 pp","保守 ΔMDD 中位 pp","保守 Δ曝險中位 pp","保守 Δturnover 中位","複雜度"],
        [[r["candidate"],r["category"],r["label"],len(r["all_three_policies_joint_improved_symbols"]),len(r["both_subperiods_all_policies_joint_improved_symbols"]),
          n(br("FULL","conservative",r["candidate"])["distributions"]["return_pp"]["median"]),n(r["median_mdd_delta_by_policy"]["conservative"]),n(r["median_exposure_delta_by_policy"]["conservative"]),
          n(r["median_turnover_delta_by_policy"]["conservative"]),r["complexity"]] for r in d["robustness"] if r["candidate"]!="A"])
    add("A 保留作正式 benchmark，未更動。C 是最清楚的 exposure-retention 結構假說，但 MDD 代價較高，不能直接稱為最合理正式 v3。E 的中位回撤代價較低、三 policy joint 改善廣度較大（6/11），但 return 中位增量小；D 提供較小回撤代價的固定梯度對照。B 用來隔離 immediate sale 的作用。四者目前都保留研究價值，沒有任何一者滿足本輪 Strong 門檻；不需要硬挑一個 winner。")
    section("12. Strategy v3 recommendation / 明確回答")
    answers=[
        ("First TP 50% immediate reduction 是否跨股票普遍拖累？","有多數但非普遍證據：B 完整期報酬改善 8/11、7/11、7/11；中位增量 +4.60、+2.42、+3.27 pp。NVDA 的 +98.64 pp 是放大特例，不是典型幅度。"),
        ("25% reduction 是否合理改善？","曝險梯度所有情境成立；完整期 return 梯度僅 8/11、7/11、7/11。D 比 50% 少截斷 winner，也較少放大反轉損失，但不證明 25% 最優，且它仍有子期反例。"),
        ("Extreme TP partial sales 是否跨股票普遍拖累？","E 完整期報酬改善 8/11、7/11、6/11，中位 +0.68、+1.04、+0.67 pp；剔除 NVDA 有利模式僅 5/10 改善，中位 +0.24 pp。方向偏正但增量通常遠小於 NVDA 的 +34.62 pp，不能稱普遍冗餘。"),
        ("Candidate C 是否最合理 v3 候選？","可保留為研究主假說，不能據此推薦 production v3：只有 5/11 檔在完整期三 policy 同時提升 Return＋Sharpe，雙子期三 policy 同時提升者只有 NVDA／META；SPY／QQQ 是穩定負向反例，回撤也常變深。"),
        ("Protective 在取消減碼後仍有 downside 價值？","是，有實際避免虧損與較小 daily-close drawdown 的證據，但 40-session 配對的整體淨效果為負、上檔成本高；保留它作防護假說比直接刪掉更可解釋，不代表成本值得每一種市場情況。"),
        ("哪些結果只在 NVDA 成立？","『收益提升超過百個百分點而 MDD 只多幾個百分點』的量級不能外推。NVDA 占 C 保守 matched 淨增量約 59.52%；多數其他標的改善後仍為負報酬。winner retention 機制並非 NVDA 獨有，AAPL／GOOGL／META／AVGO／AMZN 的具體大 winner 也受益。"),
        ("哪些結果跨 symbols／periods／policies 一致？","曝險隨 50→25→0 上升最一致；完整五年中位改善也不只靠 NVDA。但 joint return/Sharpe 的跨兩子期三 policy 一致性，B/C/D 僅 NVDA＋META；E 為 NVDA＋META＋TSLA。沒有全 11 標的跨所有維度一致的優勝結構。")]
    for i,(q,a) in enumerate(answers,1):
        add(f'\n{i}. **{q}** {a}')
    add("\n下一步若繼續研究，應保留 C 的結構假說及 D/E 低減碼對照，先驗證未參與本輪判斷的股票族群與時間，而不是開始搜尋最佳 3%／partial／MA 參數。本輪沒有執行新的調參、walk-forward 或 production v3。")
    section("13. Limitations / reproducibility / validation")
    add("\n".join("- "+s for s in [
        "這是事後描述性研究，候選來自 NVDA 既有結果；不是 preregistered 未看資料的 out-of-sample 檢定。分類 cutoff 在本輪計算前寫入，但不能消除先前選擇偏誤。",
        "11 個指定符號是當代大型成長股與含有它們的 ETF，存在存活者／選樣偏差、科技因子共振與 ETF 成分重疊，不能當 11 個獨立實驗。",
        "兩個子期間含混合行情，非純 bull/bear，也不是 walk-forward。不能因某股票 buy&hold 大漲就預測 C 必勝。",
        "Daily OHLC 三 policy 沿用正式版本而非新 tick simulator；已知 order-assumption 邊界仍在。未拿這次敏感度結果重寫 Conservative。",
        "Yahoo 資料非 point-in-time，可能事後修訂；價格調整合約採同一正式程式口徑，沒有逐日獨立復核公司行動。Warm-up、日期、hash 可重現，但不可據此宣稱資料零誤差。",
        "配對部位可相互重疊，美元加總不受共同資金約束；另附 entry-notional 正規化，不把它當投組績效。Full-winner/loser 分組是事後描述。",
        "固定 40 日避免五年末端主導，但不能消除 horizon-dependence。行政清倉與自然退出要分辨；31 個不足期限 entry 不納入主估計。",
        "higher exposure 不等於更好風險調整結果；絕對多數標的仍有負報酬，不能只報相對 Full 改善。沒有因資料或報酬差而調整任何股票參數。",
        "本輪唯一新 cache 是指定未快取 ticker 的 Yahoo daily；pre-existing caches、production app、DB/backtests/position_audits 全部未改。No Browser Use。"
    ]))
    add("\n重現（先使用已凍結的 Parquet，不重新下載）：\n")
    add("```text\npython -B -m research.run_structural\npython -B -m research.structural_report\npython -B -m pytest research/tests -q -p no:cacheprovider\n```\n")
    add("Python 使用 backend/.venv；研究 JSON／Markdown 由 stdout 輸出供保存，不建立正式 backtest ID，不寫入 database。首次資料取得使用 `python -B -m research.structural_data --acquire-network` 與正式 ProviderChain；研究重跑只讀 `first-tp-structural-inputs.json` 指定的檔案並驗 hash。下載不能替換本輪凍結資料。")
    add(f'\n本次數值研究 runtime：{n(d["runtime_seconds"])} 秒（不含首次資料下載、測試／文件輸出）。495 組 portfolio + 800 anchors × 3 policies 的兩套 lifecycle 比較。完整 SHA-256 證據存於 JSON `immutability`：')
    for k,v in d["immutability"]["after"].items():
        add(f'\n- {k}: `{v}`')
    add("\n\nCanonical Simple／Advanced executions differences=0，net PnL differences=0，equity differences=0，metrics differences=0；historical backtests／position audits logical hash unchanged。\n")
    if validation:
        tbl(["驗證","結果"],[[k,v] for k,v in validation.items()])
    else:
        add("測試與 build 結果由最終 validation 記錄附於此節，不依據推測填寫。")
    return "\n".join(lines).strip()+"\n"


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    data=json.loads((ROOT/"data/first-tp-structural-robustness.json").read_text(encoding="utf-8"))
    path=ROOT/"data/first-tp-structural-validation.json"
    validation=json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    print(render(data,validation),end="")
