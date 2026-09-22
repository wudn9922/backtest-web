"""Render the saved research artifacts to Markdown on stdout (no writes)."""
import json
import sys
from research import ROOT


def n(x, digits=2):
    return "—" if x is None else f"{x:,.{digits}f}"


def pct(x):
    return "—" if x is None else n(x*100)+"%"


def table(headers, rows):
    def cell(v):
        return str(v).replace("|", "\\|").replace("\n", " ")
    return "\n"+"| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)+"\n"


def common(d):
    a = d["canonical"]["advanced"]
    text = "## 凍結基準與方法\n\nNVDA，2021-09-01～2026-09-01，Strategy Version 2。固定原始日線快取、187 根暖機與 1,255 根研究日線；相同進場區間、初始 $100,000、配置 100%、手續費 0.05%、滑價 0.02%。所有策略参数保持原值，沒有參數搜尋。\n"
    text += table(["Canonical", "Backtest ID", "報酬", "CAGR", "MDD", "Sharpe", "交易數"],
        [[name, x["backtest_id"], pct(x["metrics"]["total_return"]), pct(x["metrics"]["cagr"]), pct(x["metrics"]["max_drawdown"]), n(x["metrics"]["sharpe_ratio"],6), x["metrics"]["number_of_positions"]] for name,x in d["canonical"].items()])
    text += "\n完整參數、價格調整、來源與快取时间戳保留於同名 JSON 的 `canonical`；未重寫任何正式回測紀錄。資料指紋：\n\n```json\n"+json.dumps(d["immutability"]["before"],indent=2)+"\n```\n"
    text += "\n完整回測保留單一持倉與再進場，包含資金路徑效應。Matched-entry 固定原始進場日／實際 P0／Q0，後續禁止第二次買進；可重疊的獨立 lifecycle 損益加總不是可交易組合，也不能直接換算 CAGR。所有損益含原手續費與滑價。\n"
    return text


def portfolio_table(rows, policy=False):
    headers=["策略變體"]+(["Policy"] if policy else [])+["Return","CAGR","MDD","Sharpe","Positions","平均股票曝險","持有天數"]
    result=table(headers,[[r["name"]]+([r["policy"]] if policy else [])+[pct(r["summary"]["total_return"]),pct(r["summary"]["cagr"]),pct(r["summary"]["max_drawdown"]),n(r["summary"]["sharpe_ratio"]),r["summary"]["number_of_positions"],n(r["exposure"]["average_close_capital_exposure_pct"])+"%",n(r["summary"]["average_holding_days"])] for r in rows])
    return result


def render_a(d):
    buckets=d["ambiguity_cost_buckets"]
    genuine=sum(v["sum_delta"] for k,v in buckets.items() if k!="IDENTIFIABLE_OR_OTHER_POLICY_DIFFERENCE")
    a=d["classifications"]["ADVANCED_FULL"]["conservative"]
    text="# Daily OHLC Intrabar Ambiguity Attribution\n\n## Executive Summary\n\n"
    text+=f"完整 Advanced：Conservative +13.39%、Heuristic +41.89%、Favorable +41.33%。完整組合 Favorable−Conservative = **{n(d['portfolio_policy_deltas']['ADVANCED_FULL']['return_difference_pp'])} 個百分點**／${n(d['portfolio_policy_deltas']['ADVANCED_FULL']['final_equity_difference'])}，但不能把資金與後續進場路徑差異全部算成單筆 ambiguity 成本。\n\n"
    text+=f"固定 canonical 77 次進場後，首個分歧日確屬 genuine ambiguity 的 lifecycle 損益差為 **${n(genuine)}**（20 筆）；其中進場日風控順序占 ${n(buckets['ENTRY_THEN_STOP_AMBIGUITY']['sum_delta'])}（19 筆），TP／stop 占 ${n(buckets['TP_VS_STOP_AMBIGUITY']['sum_delta'])}（1 筆）。另有3筆可由收盤判定的policy差異合計 ${n(buckets['IDENTIFIABLE_OR_OTHER_POLICY_DIFFERENCE']['sum_delta'])}，**不計入 genuine ambiguity**。\n\n"
    text+="移除 First TP family 的報酬改善在三種模式均為正且最大；Simple 在三種模式也都高於完整 Advanced。因此 winner truncation 的方向不是 Conservative 單獨造成的。保守模式在此樣本較悲觀，但不是已證實偏離真實成交的估計量；沒有 tick 真值，不能宣稱統計顯著或應改正式 policy。\n\n"
    text+=common(d)
    text+="\n## A1. Genuine ambiguity 分類\n\n分類讀取該日開盤實際持倉狀態及既有門檻，不改任何成交。可重疊類別與互斥歸因 bucket 分開保存。\n"
    text+=table(["類別","可辨識判準"],[
        ["ENTRY_THEN_STOP_AMBIGUITY","空手開盤；O<Entry、H≥Entry、L≤有效stop，且收盤未迫使再次越過stop。Low在進場前／後皆可行。"],
        ["TP_VS_STOP_AMBIGUITY","有效停利與風控均被觸及，開盤不能確定先後；或新protective的Low可能發生於First TP啟用前／後。"],
        ["MULTI_THRESHOLD_AMBIGUITY","上述genuine情形另有至少3個觸及的有效／依FirstTP啟動門檻，不同順序能改變數量或regime。只作重疊標籤，不能重複加總成本。"],
        ["NON_AMBIGUOUS","無持倉／無進場、Open>UpperEntry、進場已在Open完成、scheduled OPEN exit、單一門檻，或開盤／收盤已唯一確定相關先後。"]])
    text+="\n特別是 O<Entry 不表示 Low 已知在 Entry 前。反過來，若 High 到達 Entry 而 Close≤Stop，無論早先 Low 在哪裡，收盤前仍必定有 post-entry stop crossing。條件順序可判定不等於其精確盤中時間可判定。多次未觀測波動仍可能存在。\n"
    text+="\n## A2/A4. 三種既有 policy × 四種策略\n\n直接調用正式三種 policy；all-on Simple/Advanced 各模式逐筆與正式 engine replay 相等。Conservative adverse-first；Heuristic 上漲日 O-L-H-C／下跌日 O-H-L-C；Favorable 使用目前實作的有利選擇。這些是**既有 threshold-order resolver**，不是完整 tick path 重建、也不是已證明的上下界；Favorable 不保證最終組合報酬最高。\n"
    text+=portfolio_table(d["portfolio"],True)
    text+=table(["策略","Policy","genuine交易","genuine交易日","engine標記日","標記但順序可判定日"],[[r["name"],r["policy"],r["ambiguous_positions"],r["ambiguous_days"],r["engine_flagged_days"],r["flagged_but_identifiable_days"]] for r in d["portfolio"]])
    text+="\n同模式下，相對完整 Advanced 的 Return 改善（百分點）：\n"
    text+=table(["Policy","Simple","Minus First TP family","Minus MA break"],[[p,n(v["SIMPLE"]),n(v["ADVANCED_MINUS_FIRST_TP_FAMILY"]),n(v["ADVANCED_MINUS_MA_BREAK"])] for p,v in d["ablation_return_improvements_pp"].items()])
    text+="\nFirst TP family 的拖累排名在此三種**既有**模式下 robust；MA family 的改善幅度對模式較敏感，但方向一致。此結論不代表對所有可能 tick 路徑、其他股票或樣本外期間都 robust。\n"
    text+="\n## A3. 所有 canonical entry-day stop 候選\n\n共22筆，19筆 genuine entry ambiguity、3筆收盤已迫使 post-entry stop。表中成交為該進場日的 actual execution price（含滑價），損益為固定進場後完整 lifecycle；H／F 是各自假設，不是已知盤中路徑。\n"
    for row in d["entry_day_cases"]:
        text+=f"\n### {row['position_id']} · {row['date']}\n"
        text+=table(["Open","High","Low","Close","Entry threshold","Stop threshold","genuine"],[[*(n(row["ohlc"][k],6) for k in ["open","high","low","close"]),n(row["entry_threshold"],6),n(row["stop_threshold"],6),"是" if row["genuine"] else "否"]])
        text+=table(["Policy","進場日成交順序","Lifecycle net PnL","最終出場日"],[[p," → ".join(f"{e['event_type']} {e['quantity']}@{n(e['price'],6)} (餘{e['position_remaining']})" for e in v["entry_day_executions"]),n(v["lifecycle_pnl"]),v["exit_date"][:10]] for p,v in row["policies"].items()])
        text+=f"\nF−C 損益：${n(row['delta_lifecycle_pnl'])}。"+("兩種順序皆可行；O<Entry 不代表 Low 必定先發生。" if row["genuine"] else "High已到Entry且Close在stop之下，收盤前必須出現進場後穿越stop，不能當作可完全免除stop的低點先行案例。")+"\n"
    text+="\n## A5. 排除 ambiguity（非可交易組合）\n\n先以全部12組中genuine日期的聯集排除各自持倉區段；這是事後選樣、不同日期與資金，不用其加總當作新回測Return。完整逐組數據見JSON `exclusion.own_path_descriptive`。更嚴格的同進場配對如下：\n"
    text+=f"\n63個 canonical Simple 進場固定 P0／Q0，所有4策略×3模式只要任一 lifecycle 有genuine ambiguity即排除，剩 {d['exclusion']['paired_retained']} 筆。\n"
    text+=table(["策略","Policy","n","平均單筆return","中位數","獨立net PnL合計"],[[name,p,v["n"],pct(v["return_distribution"]["mean"]),pct(v["return_distribution"]["median"]),n(v["sum_net_pnl_NOT_portfolio"])] for name,policies in d["exclusion"]["paired_summary"].items() for p,v in policies.items()])
    text+=f"\n因目前policy對部分可判定日也會產生差異，再移除任何策略在三模式成交序列不一致的anchor，留下 **{d['exclusion']['paired_policy_stable_retained']}筆** 的更乾淨共同cohort：\n"
    text+=table(["策略","n","平均單筆return","中位數","net PnL合計"],[[name,v["n"],pct(v["return_distribution"]["mean"]),pct(v["return_distribution"]["median"]),n(v["sum_net_pnl_NOT_portfolio"])] for name,v in d["exclusion"]["paired_policy_stable_summary"].items()])
    text+="\nSimple 的平均單筆與合計損益仍大幅較高，但 Advanced 中位數較好：仍是 winner tail 與損失控制之間的差異，不能用『每笔Advanced都更差』概括。此cohort排除了完整大趨勢episode時會有選樣偏誤。\n"
    text+="\n## A6. 固定77進場的ambiguity成本\n\n以首個成交分歧日的genuine類別互斥歸因；entry優先於TP/stop，再other/multi，不重複計入。金額 F−C，非單一事件立即收益，而是同筆後續lifecycle差。\n"
    text+=table(["首次分歧類別","影響筆數","合計","平均","中位數"],[[k,v["count"],n(v["sum_delta"]),n(v["distribution"]["mean"]),n(v["distribution"]["median"])] for k,v in buckets.items()])
    for name,v in buckets.items():
        text+=f"\n### {name}：最大10個絕對差異\n"+table(["Position","首次分歧日","F−C PnL"],[[x["position_id"],x["date"],n(x["delta"])] for x in v["largest_10"]])
    text+="\n### 不能歸因為 genuine ambiguity 的3筆\n\nposition-3（2021-12-09）、position-9（2022-02-18）、position-17（2023-02-21）：Close已在MA half-stop以下。既有Favorable的entry resolver依Open<Entry選low-before-entry，因此仍有policy差異；本輪**只揭露並另列**，沒有改policy、策略或historical結果。這也意味三模式整體spread不是純粹的不可識別OHLC成本。\n"
    text+="\n## 回答與限制\n\n1. Advanced完整F−C差27.94pp；固定77筆genuine部分+$26,428.99，不能用它除以組合損益差硬算『解釋百分比』。\n2. Entry-day是主要genuine來源：19筆+$24,662.48，約占上述genuine matched金額93.32%。\n3. Conservative在本NVDA樣本明顯壓低結果；沒有tick真值，不能證明其偏誤大小、顯著性或Favorable較真實。\n4. 排除genuine、再排除其他policy成交差異後，Simple仍以winner tail取得更高平均與合計損益。\n5. FirstTP family拖累方向與本研究的ablation第一名跨三模式一致。\n\n單股、單區間、事後cohort、固定曆日終點、政策非完整路徑、未觀測日內價格往返都是限制。MFE/MAE或High存在不代表可在該價成交；本研究不做優化或正式規則修改。\n"
    return text


def render_b(d):
    text="# First TP Family Decomposition\n\n## Executive Summary\n\n"
    text+="取消立即50%減倉、保留FirstTP signal／Protective／Extreme，Return **13.39% →112.02%**（+98.64pp），MDD **−22.95% →−24.27%**；固定77個進場只有11筆實際受到立即減倉影響，合計+$82,984.95，全部77筆中位數0、受影響11筆中位數+$831.85。\n\n取消Extreme、保留FirstTP50%與Protective，Return變48.01%（+34.62pp），MDD−23.95%，固定進場+$33,079.49（8筆）。取消Protective雖得191.69%，但完整回測只剩1筆持倉，固定進場20筆變化中16筆被推到研究期末；**不能把它當作可靠的單獨Protective價值估計**。\n\n最清楚的可辨識拖累是立即減半與後續極端分批降低winner exposure；Protective／整體regime的效果更大但受終點與狀態互動混淆，不能直接刪掉規則。\n"
    text+=common(d)
    text+="\n## B1. 合法研究設計與dependency\n\nP=+3%時立即賣出50% CURRENT（整股規則不變）；S=Protective；E=Bias及ATR。所有8格固定+3% signal，均遵守正式signal之後停止原MA half/Break迴圈的regime切換。Volume／Day2及成本不變。沒有S時**不偷偷重新啟用MA half-stop**；因此可能直到期末才全數平倉。E依signal獨立rearm、原Q0數量、20%限制和max3保持不變。P關閉只是取消該次sale，絕不取消signal。\n\nFIRST_TP_PARTIAL_NO_PROTECTIVE與PROTECTIVE_OFF在合法語意下相同，明確作alias，不能當作兩個獨立證據。另補齊8個布林模組組合，以difference-in-differences量化交互作用；這是固定參數ablation，不是參數sweep。\n"
    text+=table(["名稱","P/S/E","備註"],[[name,v["factorial_cell"],"相同變體的alias" if name=="PROTECTIVE_OFF" else ("保留+3%signal；沒有post-TP風控，期末參照" if v["factorial_cell"]=="P0S0E0" else "僅研究，不註冊至正式API") ] for name,v in d["variant_definitions"].items()])
    text+="\nSIGNAL_ONLY_FULL_RISK_REFERENCE定義為進入FirstTP regime後不減倉／無Protective／無Extreme；不是原先MINUS_FIRST_TP_FAMILY（後者保留前TP的MA風控迴圈）。兩者不能混用。\n"
    text+="\n## B3. 完整回測績效\n"+portfolio_table(d["portfolio"])
    text+=table(["變體","ΔReturn pp","ΔMDD pp","Win rate","PF","Turnover雙邊","Commission","Slippage"],[[r["name"],n(r["delta_vs_full"]["total_return"]*100),n(r["delta_vs_full"]["max_drawdown"]*100),pct(r["summary"]["win_rate"]),n(r["summary"]["profit_factor"]),n(r["exposure"]["two_sided_turnover"]),n(r["summary"]["total_commission"]),n(r["summary"]["estimated_slippage_cost"])] for r in d["portfolio"]])
    text+="\n曝險為每日收盤股票市值／當日總權益的平均；持有天數沿用正式calendar-day metric。Turnover為研究期買賣總成交額／平均每日權益，非年化。交易成本包含原滑價，沒有額外雙扣。\n"
    text+="\n## B4. Canonical77進場的matched結果\n\nDelta=變體−Full。winner／loser依原Full net PnL分組；中位數含未受影響的0，不應誤解成規則毫無效果。\n"
    text+=table(["變體","改變筆數","Sum delta","平均/77","中位數/77","Full winners delta","Full losers delta","出場日改变","改變者期末平倉"],[[name,v["changed_anchors"],n(v["sum_delta"]),n(v["delta"]["mean"]),n(v["delta"]["median"]),n(v["winner_delta"]),n(v["loser_delta"]),v["exit_date_changes"],v["terminal_closes"]] for name,v in d["matched"]["summary"].items()])
    for name,v in d["matched"]["summary"].items():
        if name in ("ADVANCED_FULL","PROTECTIVE_OFF"):continue
        text+=f"\n### {name}：Top positive / negative\n\n正向樣本{len(v['top_positive'])}筆、負向樣本{len(v['top_negative'])}筆（各最多10筆；不足10不補零）。\n"
        text+=table(["方向","Position","PnL delta"],[["正",x["position_id"],n(x["delta"])] for x in v["top_positive"]]+[["負",x["position_id"],n(x["delta"])] for x in v["top_negative"]])
    text+="\n## B2. Marginal effect與interaction\n\n下表為**啟用on−停用off**，其餘模組完全固定。正MDD reduction代表減少回撤；金額仍是77個獨立lifecycle。\n"
    text+=table(["Module","Off → On","Return effect pp","MDD reduction pp","Matched PnL effect","曝險 effect pp"],[[r["module"],r["off"]+" → "+r["on"],n(r["return_effect_pp"]),n(r["mdd_reduction_pp"]),n(r["matched_sum_on_minus_off"]),n(r["exposure_effect_pp"])] for r in d["marginal_effects"]])
    text+="\n在完整downstream背景下，立即50%減倉犧牲98.64pp Return，換來1.32pp MDD縮減；Extreme犧牲34.62pp，換來1.00pp MDD縮減。沒有Extreme時，立即50%的Return effect是−127.05pp：不能直接把−98.64與−34.62相加解釋所有變體。\n"
    text+=table(["交互項","Return差分pp","Matched PnL差分"],[[k,n(v*100),n(d["factorial_interactions"]["matched_pnl"][k])] for k,v in d["factorial_interactions"]["total_return"].items()])
    text+="\nP×E（S=1）+28.42pp、matched +$6,076.01：已有一層減倉會壓縮另一層的邊際效果。含S=0的大交互項高度受一筆長持／期末平倉支配，不是可相加的固定『規則貢獻』。\n"
    text+="\n## B5. 大型winner的股數軌跡\n\n選擇full-risk參照PnL前5名，再加入canonical Full獲利前3名（去重）。以下列出進場、出場、任一variant股數改變日；**同名JSON保存每個交易日**，包括完全沒事件的日期。股數為收盤後剩餘，不是成交前；已平倉的variant後續為0，禁止再進場。價格為當日收盤。\n"
    for item in d["winner_quantity_trajectories"]:
        text+=f"\n### {item['position_id']} · P0={n(item['p0'],6)} · Q0={item['q0']}\n"
        rows=[];prev=None
        for row in item["daily"]:
            qty=tuple(row[k+"_qty"] for k in ["full","no_50_partial","no_protective","no_extreme"])
            if qty!=prev or any(row["executions"].values()) or row is item["daily"][-1]:
                events="; ".join(k+":"+",".join(f"{e['event_type']} {e['quantity']}" for e in ex) for k,ex in row["executions"].items() if ex)
                rows.append([row["date"],n(row["close"],4),*qty,events or "持續持有"])
            prev=qty
        text+=table(["Date","Close","Full qty","No50 qty","NoProtective qty","NoExtreme qty","成交摘要"],rows)
    text+="\n## B6. MDD trade-off與loss prevention\n"
    text+=table(["變體","MDD","Start","Trough","Recovery"],[[r["name"],pct(r["summary"]["max_drawdown"]),r["drawdown_episodes"][0]["start"],r["drawdown_episodes"][0]["trough"],r["drawdown_episodes"][0]["recovery"] or "尚未恢復"] for r in d["portfolio"]])
    text+=table(["變體","參照losers n","避免最終損失","參照winners n","犧牲上漲損益"],[[r["variant"],r["reference_losers"],n(r["loss_avoided"]),r["reference_winners"],n(r["upside_sacrificed"])] for r in d["risk_tradeoffs"]])
    text+="\n上述full-risk參照下41筆loser全部在FirstTP之前被原有confirmation／MA風控處理，故family variants的『避免最終損失』皆0。這**不代表沒有途中回撤保護**：16筆延長至期末的交易最後大漲，期間風險已被終點net PnL掩蓋。reference單筆長持MDD−66.33%，signal+Protective/no partial/no Extreme為−25.93%（約40.40pp改善），所以Protective具限制長期downside exposure的機制价值，但這仍是不同portfolio path比較，不能據此宣稱最佳规则。\n\nImmediate50與Extreme在保留Protective時只各提供約1～2pp MDD改善，卻切掉較多winner上漲。就本樣本研究優先序，最值得先釐清**立即50%減倉是否必要**；再研究Protective啟動與原MA風控regime切換的交互作用。保留Protective作風險約束的研究價值高於直接取消它，但尚不足以宣稱可部署或樣本外最優。\n"
    text+="\n## 結論、曝險與限制\n\nFull平均股票曝險12.68%；No50升至21.05%；NoExtreme升至16.92%；No50+NoExtreme升至25.10%。退出日期未變而股數提高的matched案例，直接支持winner truncation／低曝險是因果機制之一，並非只有confirmation filter。\n\n最大的可解釋問題是**立即減半、later partials與保護性出場的交互低曝險regime**。不能以Protective-off超大matched金額直接判其最差：長期重疊counterfactual、16筆期末截尾、單股大多頭與一筆portfolio都會放大該數值。關掉整個FirstTP family又會恢復持續的原MA風控，因此也不等於三個邊際效果相加。\n\n下一步只建議針對現有固定規則的機制繼續研究，不在本輪改production或搜尋參數。\n"
    return text


def render(phase, data):
    body = render_a(data) if phase == "A" else render_b(data)
    return body.replace("参数","參數").replace("时间","時間").replace("每笔","每筆").replace("改变","改變").replace("价值","價值").replace("规则","規則") + "\n## 驗證與不變性\n\nResearch tests 42 passed；backend 142 passed（2個既有相依套件deprecation warnings）；frontend 25 passed；production build passed。正式Simple／Advanced的executions、數量、價格、net PnL、equity與metrics差異均0；資料庫、position audits、日線Parquet及全部backend source指紋完全相同。三種policy的all-on research replay亦逐筆對上正式engine。沒有改正式policy或任何historical records。\n\nFrontend繁中顯示層與本研究模擬完全分離。未使用Browser Use；手機視覺、觸控與實機排版仍需人工確認，CLI測試不冒充視覺驗證。\n"


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    phase=sys.argv[1]
    name="intrabar-ambiguity-attribution" if phase=="A" else "first-tp-family-decomposition"
    data=json.loads((ROOT/"data"/(name+".json")).read_text(encoding="utf-8"))
    print(render(phase,data))
