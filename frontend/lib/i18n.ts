/** Display-only translations. Never translate request values, event codes or exports. */
export const locale = "zh-TW";
export const zhTW: Record<string, string> = {
  "Parameter optimization":"參數最佳化", "MA period optimization":"均線週期最佳化", "Optimization history":"最佳化紀錄",
  "Run optimization":"執行最佳化", "Running MA optimization":"正在執行均線最佳化", "Minimum period":"最小週期", "Maximum period":"最大週期", "Step":"步長",
  "This run will execute":"本次將執行", "backtests":"組回測", "Maximum 500 backtests per run.":"每次最多執行 500 組回測。",
  "Ranking metric":"排序依據", "Best result":"目前最佳", "Ranked by":"排名依據", "Nearby parameter performance":"附近參數表現",
  "均線選擇方式":"均線選擇方式", "依回測績效":"依回測績效", "依 K 線結構":"依 K 線結構", "Structure selection is available only for Rolling 6M.":"結構選擇僅支援 Rolling 6M。",
  "K 線結構檢視":"K 線結構檢視", "K 線結構分數":"K 線結構分數", "多空分界能力":"多空分界能力", "均線回測能力":"均線回測能力", "突破後 +3%":"突破後 +3%", "第二日確認一致性":"第二日確認一致性",
  "Retest Wilson":"回測 Wilson 下界", "Breakout Wilson":"突破 Wilson 下界", "Retest events":"回測事件", "Confirmation resolved":"確認已解決事件", "Confirmation violation rate":"確認違反率", "Bull / bear breakouts":"多方／空方突破", "Gap / missed":"跳空／錯過", "Execution feasibility":"成交可行性",
  "Performance OOS aggregate":"Performance 樣本外彙總", "Structure OOS aggregate":"Structure 樣本外彙總", "Structure − Performance":"Structure − Performance", "Fixed MA OOS aggregate":"固定均線樣本外彙總", "Frozen Structure specification":"凍結結構規格",
  "結構突破次數":"結構突破次數", "成功突破":"成功突破", "失敗突破":"失敗突破", "未完成事件":"未完成事件", "可成交突破":"可成交突破", "跳空突破":"跳空突破", "跳空錯過":"跳空錯過", "事件樣本數":"事件樣本數", "Wilson 下界":"Wilson 下界",
  "No Structure chart data":"目前沒有 K 線結構圖資料", "Numerical OHLC audit only":"僅供數值 OHLC 稽核", "Fullscreen chart":"全螢幕檢視", "Exit fullscreen":"離開全螢幕", "Chart markers come from numerical backend events and are for visual audit only.":"圖表標記來自後端數值事件，僅供人工稽核。", "Retrospective OOS comparison; does not establish future predictive ability.":"回溯式樣本外比較，不代表未來預測能力。", "Train performance reference only":"Train 績效僅供參考", "Train performance is reference only and does not participate in Structure selection.":"Train 績效僅供參考，不參與結構選擇。",
  "Nearby parameters are relatively stable":"附近參數表現相對穩定", "Stability around this optimum is low":"此最佳值附近穩定性較低",
  "Out-of-sample validation":"樣本外驗證", "Optional; disabled by default":"可選功能，預設關閉", "Training period":"訓練區間", "Test period":"測試區間",
  "Training start":"訓練開始", "Training end":"訓練結束", "Test start":"測試開始", "Test end":"測試結束", "Train best":"訓練區間最佳", "Test performance":"測試區間表現",
  "Test data is never used to select the best MA period.":"測試資料不會參與最佳均線週期的選擇。",
  "MA performance chart":"均線績效圖", "Equity curve comparison":"權益曲線比較", "Select up to five MA periods":"最多選擇 5 個均線週期", "No curve selected":"尚未選擇比較曲線",
  "View full backtest":"查看完整回測", "Apply this MA":"套用此均線", "Cancel optimization":"取消最佳化", "Refresh":"重新整理",
  "Completed":"已完成", "Failed":"失敗", "Current":"目前", "Best does not mean future-optimal or production-validated.":"此處最佳僅代表所選排序指標，不代表未來最佳或已通過實盤驗證。",
  "The optimizer changes only MA period and calls the canonical backtest engine for every row.":"最佳化工具只改變均線週期；每一列都直接呼叫正式回測引擎。",
  "Fixed strategy parameters":"固定策略參數", "Search settings":"搜尋設定", "Optimization results":"最佳化結果", "Open optimization":"開啟最佳化", "No optimization history yet.":"目前沒有最佳化紀錄。",
  "Optimization could not start.":"無法開始最佳化。", "Optimization result unavailable":"最佳化結果尚未完成", "Cached result":"沿用相同資料指紋的快取結果",
  "Could not open backtest":"無法開啟回測",
  "Skipped / insufficient history":"略過／歷史資料不足", "Retry optimization":"使用原設定重試", "Failure reason":"失敗原因", "Failure stage":"失敗階段",
  "DATA_PREPARATION":"資料準備", "CANONICAL_BACKTEST":"正式回測引擎", "Historical warm-up":"指標歷史預熱",
  "MARKET_DATA_PROVIDERS_UNAVAILABLE":"市場資料來源目前無法補齊缺少的日線資料", "NOT_ENOUGH_MA_LOOKBACK":"均線歷史資料不足", "NOT_ENOUGH_BIAS_HISTORY":"乖離指標歷史資料不足", "NOT_ENOUGH_ATR_HISTORY":"ATR 歷史資料不足",
  "The saved job includes Train/Test validation.":"這筆工作包含樣本外驗證；資料準備範圍會從訓練區間開始，而不是一般回測的開始日期。",
  "Optimization method":"最佳化方式", "Single Train / Test":"單次 Train／Test", "Re-optimize every 6 months":"每 6 個月重新最佳化",
  "Use the prior 6 calendar months to select the best MA, then hold that MA fixed for the next 6 calendar months.":"使用前 6 個曆月找出最佳均線，並固定套用於接下來 6 個曆月。",
  "Each training window will execute":"每個訓練區間將執行", "Fixed MA comparison":"固定均線比較值",
  "Independent test segments":"獨立測試區間", "Each 6-month test segment starts flat. Segment-chained return is not continuous portfolio execution and positions do not carry across boundaries.":"每個 6 個月測試區間都獨立從空倉開始。分段串接報酬不是連續投資組合，持倉不會跨越期間邊界。",
  "Running rolling 6-month optimization":"正在執行每 6 個月滾動最佳化", "Window":"期間", "TRAIN":"訓練搜尋", "WINDOW_COMPLETE":"期間完成",
  "Only each prior 6-month training segment selects the MA used in the following 6-month test segment.":"每一期只使用先前 6 個月的訓練資料，選擇下一個 6 個月測試使用的均線。",
  "Rolling optimization summary":"滾動最佳化摘要", "Test-only aggregate":"樣本外測試彙總", "complete test windows":"個完整測試區間",
  "Positive test windows":"測試正報酬", "Average test return":"平均測試報酬", "Median test return":"測試報酬中位數", "Average test Sharpe":"平均測試夏普",
  "Worst 6-month return":"最差 6 個月", "Best 6-month return":"最佳 6 個月", "Selected MA median":"入選均線中位數", "Selected MA range":"入選均線範圍",
  "6-month segment-chained OOS return":"6 個月分段串接樣本外報酬", "This geometrically chains independent test segment returns. It is not continuous portfolio equity and carries no position across a six-month boundary.":"此數值僅將各獨立測試區間的報酬作幾何串接；它不是連續投資組合權益，也不會把持倉帶過六個月邊界。",
  "Selected MA history":"入選均線歷史", "Selected MA":"入選均線", "Train to test relationship":"訓練與測試關係",
  "Train/Test metric correlation":"訓練／測試指標相關", "Train/Test return correlation":"訓練／測試報酬相關", "Positive test return ratio":"測試正報酬比例", "Test Sharpe above zero":"測試夏普大於零",
  "Test Sharpe above 1.0":"測試夏普大於 1.0", "Fixed MA chained return":"固定均線分段串接報酬", "Rolling minus fixed MA":"滾動最佳化減固定均線",
  "MA standard deviation":"均線週期標準差", "Average adjacent MA change":"相鄰期間平均 MA 變化", "These are descriptive statistics only and never alter MA selection.":"以上僅為描述統計，不會改變任何期間的均線選擇。",
  "STRUCTURE_SCORE":"結構分數較高", "HIGHER_BREAKOUT_WILSON":"突破 Wilson 下界較高", "MORE_RESOLVED_EVENTS":"已解決結構事件較多", "LOWER_CONFIRMATION_VIOLATION":"確認違反率較低", "CANONICAL_CANDIDATE_ORDER":"候選均線原始順序", "PRIOR_INVALIDATED_IMPLEMENTATION":"此結果由舊版結構實作產生，已失效；請重新執行。",
  "Performance vs Structure comparison":"Performance 與 Structure 比較", "Structure is selected from Train OHLC only; all Test rows use the canonical engine from flat.":"Structure 僅使用 Train OHLC 選擇；所有 Test 列均由空倉正式引擎執行。", "Performance-selected MA":"Performance 入選均線", "Structure-selected MA":"Structure 入選均線", "Performance Test return":"Performance 測試報酬", "Structure Test return":"Structure 測試報酬", "Structure − Performance return":"Structure − Performance 報酬", "Structure − Performance Sharpe":"Structure − Performance 夏普",
  "Structure candidate details":"Structure 候選詳細資料", "Bull regime":"多方 regime", "Bear regime":"空方 regime", "Bull retest":"多方回測", "Bear retest":"空方回測", "Bull breakout":"多方突破", "Bear breakout":"空方突破", "Bull Wilson":"多方 Wilson 下界", "Bear Wilson":"空方 Wilson 下界",
  "6-month rolling results":"6 個月滾動結果", "Each test segment is an independent canonical backtest that starts flat.":"每個測試區間都是從空倉開始的獨立正式引擎回測。",
  "Train period":"訓練區間", "Train metric":"訓練排序指標", "Train Sharpe":"訓練夏普", "Train return":"訓練報酬", "Test Sharpe":"測試夏普", "Test return":"測試報酬", "Test MDD":"測試最大回撤", "Test Net PnL":"測試淨損益", "Fixed MA return":"固定均線報酬",
  "View complete test backtest":"查看測試區間完整回測", "Test":"測試", "Train":"訓練", "Expand train MA ranking":"展開訓練均線排名", "Tie-break reason":"同分決定方式", "Actual train sessions":"實際訓練交易日",
  "RANKING_METRIC":"排序指標較佳", "HIGHER_TOTAL_RETURN":"總報酬較高", "LOWER_ABSOLUTE_MDD":"絕對最大回撤較低", "SMALLER_MA_PERIOD":"均線週期較小",
  "PROVISIONAL_PARTIAL_TEST":"未完成測試區間", "NO_VALID_TRAIN_RESULT":"訓練區間無有效結果", "TEST_FAILED":"測試區間執行失敗",
  "Maximum drawdown":"最大回撤", "Number of trades":"交易次數", "Average holding days":"平均持有天數",
  "MA_PERIOD_OPTIMIZATION":"均線週期最佳化", "Canonical engine":"正式回測引擎", "Back to optimizer":"返回參數最佳化",
  "Volatility-managed exposure benchmark study":"波動度管理曝險基準研究",
  "20-day volatility-managed exposure":"20 日波動度管理曝險",
  "20-day realized volatility":"20 日波動度",
  "15% target volatility":"15% 目標波動",
  "Maximum 100% equity exposure":"最高 100% 股票曝險",
  "Remaining allocation held as cash":"剩餘資金持有現金",
  "SPY Sharpe delta":"SPY 夏普差異",
  "SPY maximum drawdown delta":"SPY 最大回撤差異",
  "SPY CAGR delta":"SPY 年化報酬差異",
  "SPY average exposure":"SPY 平均曝險",
  "ETF Sharpe improvement":"ETF 夏普改善",
  "ETF MDD improvement":"ETF 最大回撤改善",
  "ETF Calmar improvement":"ETF Calmar 改善",
  "Cash-yield contribution":"現金利息貢獻",
  "Incremental effect":"相對增量",
  "Crisis behavior":"危機期間表現",
  "episodes reduced maximum drawdown":"個危機期間降低最大回撤",
  "Lowest target exposure":"最低目標曝險",
  "Cost attribution":"成本歸因",
  "Commission and slippage":"手續費與滑價",
  "Cross-sectional momentum benchmark study":"橫斷面動能基準研究",
  "12-1 relative strength Top 3":"12-1 相對強弱 Top 3",
  "Eligible ETF equal-weight":"合格 ETF 全體等權",
  "QQQ Buy & Hold":"QQQ 買進持有",
  "Zero-interest cash":"現金不計息",
  "Treasury-proxy cash yield":"現金按國庫券利率計息",
  "Monthly completed ranking, next-open execution; all comparisons share warm-up and costs.":"每月底使用已完成價格排名，次一交易日開盤換倉；所有比較使用相同暖機起點與交易成本。",
  "Backtest Lab":"回測實驗室", "Backtest Lab — MA Breakout Research":"回測實驗室 — 均線突破研究",
  "No-lookahead moving-average breakout strategy research dashboard.":"使用已完成資料、避免前視偏誤的均線突破策略研究平台。",
  "Run no-lookahead moving-average breakout research from desktop or mobile.":"從電腦或手機執行避免前視偏誤的均線突破回測研究。",
  "NO-LOOKAHEAD QUANT RESEARCH":"避免前視偏誤的量化研究", "MA Breakout Research Workspace":"均線突破研究工作區",
  "Overview":"總覽", "Chart":"圖表", "Trades":"交易", "Events":"事件", "Parameters":"參數", "Diagnostic":"診斷", "Diagnostics":"診斷", "History":"歷史紀錄",
  "Dashboard":"研究總覽", "Backtest":"回測", "Research":"研究", "Strategy":"策略", "Simple":"簡易策略", "Advanced":"進階策略",
  "Research baseline strategy":"研究基準策略", "Historical research did not pass the strategy viability gate and does not imply suitability for real trading.":"歷史研究未通過策略可行性門檻，不代表適合實際交易。",
  "Research Framework v2":"研究框架 v2", "Research candidates":"研究候選", "Research baselines":"研究基準", "Strategy comparison":"策略比較", "Cross-asset":"跨標的", "Cross-period":"跨期間", "Cost stress":"成本壓力測試", "Daily OHLC ordering sensitivity":"日 K 順序敏感度", "Winner concentration":"Winner concentration", "Historical research":"歷史研究", "Data provenance":"資料來源追溯", "Research protocol":"研究流程", "Viability gate":"可行性門檻", "Benchmark suite":"固定基準組", "Back to backtest":"返回回測", "Loading research framework…":"正在載入研究框架…", "Research framework unavailable":"研究框架目前無法載入", "Frozen":"已凍結", "Rejected":"未通過", "Tested":"已測試", "Read-only":"唯讀", "Append-only registry":"只允許新增的 registry", "No new candidate was created in this phase.":"本階段沒有建立新策略候選。", "Production selector":"正式回測選單", "Not listed":"未列入", "Still runnable as a frozen baseline":"仍可作為凍結基準執行回測", "Open report":"開啟報告", "Report fingerprint":"報告指紋", "Common cached coverage":"共同快取涵蓋", "Preferred coverage":"優先資料範圍", "Limited cache coverage":"快取涵蓋有限", "Dataset fingerprint":"資料指紋", "Adjustment mode":"價格調整方式", "Downloaded":"下載時間", "All sensitive strategies must run every policy.":"凡結果受日 K 事件順序影響的策略，必須同時執行全部三種模式。", "Specification before results":"先寫規格，再看結果", "Any semantic change requires a new candidate ID.":"任何交易語意變更都必須建立新的 candidate ID。", "Research candidates never enter the production selector automatically.":"研究候選不得自動進入正式策略選單。", "Fixed universe":"固定研究標的", "Fixed time checks":"固定時間穩健性檢查", "Calendar year · rolling 6M · rolling 12M":"曆年・滾動 6 個月・滾動 12 個月", "Baseline · 2× commission · 2× slippage · 2× both":"基準・2 倍手續費・2 倍滑價・兩者皆 2 倍", "Top 1 / 3 / 5 / 10 and trimmed checks":"Top 1／3／5／10 與截尾檢查", "No single performance metric can pass the gate.":"任何單一績效指標都不足以通過門檻。", "Role":"角色", "Deployment":"部署狀態", "Spec hash":"規格雜湊", "Family":"策略家族", "Hypothesis":"研究假說", "Benchmarks are research comparators, not production strategies.":"這些基準只用於研究比較，不是正式交易策略。", "Prior completed levels":"只使用前一日已完成門檻", "Next-open execution":"次一交易日開盤成交", "Policy-sensitive":"受日 K 順序影響", "Policy-independent":"不受日 K 順序影響", "Data refresh pending":"等待一致口徑的資料更新", "Earlier bars were not fabricated.":"較早期資料未被偽造或補值。", "Historical results were indexed without recalculation.":"既有研究結果僅建立索引，沒有重新計算。", "Technical contract":"技術契約",
  "RESEARCH_BASELINE":"研究基準策略", "FROZEN_RESEARCH_BASELINE":"凍結研究基準", "TESTED":"已測試", "REJECTED":"未通過", "MA_BREAKOUT":"均線突破", "ADVANCED_BREAK_PROTECTION_ABLATION":"進階跌破保護拆解",
  "Buy & Hold":"買進持有", "SPY Buy & Hold":"SPY 買進持有", "200-day MA trend benchmark":"200 日均線趨勢基準", "Donchian 20/10 benchmark":"Donchian 20／10 基準",
  "Buy maximum affordable whole shares on the first study-session open and sell on the final close.":"於研究區間第一個交易日開盤買進可負擔的最大整股股數，最後一日收盤賣出。",
  "Apply the same costed Buy & Hold contract to SPY over the identical comparison dates.":"在完全相同的比較日期，以相同成本模型執行 SPY 買進持有。",
  "Close(t) > SMA200(t) schedules long at t+1 open; Close(t) <= SMA200(t) schedules cash at t+1 open.":"收盤價(t) > SMA200(t) 時，排定次一交易日開盤做多；否則排定次一交易日開盤轉為現金。",
  "Long on a 20-session high breakout; exit on a 10-session low. Both thresholds exclude the current bar.":"突破前 20 個已完成交易日高點時做多；跌破前 10 個已完成交易日低點時出場，兩個門檻都排除當日。",
  "None; opening and final-closing prices are known only at their execution phase.":"不使用未來資料；開盤與最終收盤價只在各自成交階段使用。",
  "No symbol strategy data selects SPY exposure.":"SPY 曝險不由個股策略資料選擇。",
  "The opening decision uses only the previous completed close and SMA200.":"開盤決策只使用前一交易日已完成的收盤價與 SMA200。",
  "At t, entry=max(high[t-20:t-1]); exit=min(low[t-10:t-1]).":"在 t 日，進場門檻為前 20 個完成交易日最高價；出場門檻為前 10 個完成交易日最低價。",
  "A completed STRATEGY_SPEC.md must be saved and hashed before any result run.":"任何結果執行前，必須先保存完成的 STRATEGY_SPEC.md 並記錄雜湊。",
  "Completed research decomposition":"研究拆解已完成", "M3 advanced to retrospective validation only":"M3 僅進入回溯式穩健性驗證", "NOT SUPPORTED":"不支持",
  "Benchmark viability study":"固定 Benchmark 可行性研究", "No candidate was created":"本輪未建立策略候選", "Candidate creation gate":"候選建立門檻", "PROMISING — FAMILY WORTH STUDYING":"有潛力 — 值得繼續研究此策略家族", "STRONG RETROSPECTIVE EVIDENCE":"強力回溯實證", "SMA200: NOT SUPPORTED; Donchian 20/10: NOT SUPPORTED; NEXT FAMILY = NONE":"SMA200：不支持；Donchian 20／10：不支持；下一個策略家族：無",
  "Research environment":"研究環境", "Data, universe and cash assumptions":"資料、標的集合與現金報酬假設", "Long-history status":"長歷史狀態", "Universe coverage":"標的集合涵蓋", "Cash model":"現金模型", "Provider status":"資料來源狀態", "Survivorship limitation":"存續者偏誤限制", "Data fingerprint":"資料指紋", "Sensitivity classification":"敏感度分類", "LONG-HISTORY VALIDATION UNAVAILABLE":"長歷史驗證不可用", "UNAVAILABLE":"不可用", "Unavailable":"不可用", "Available":"可用", "Not a point-in-time universe":"不是歷史時點成分集合", "Cash balance only; no double accrual":"僅現金餘額計息，不重複計入持倉資金", "Yahoo adjusted OHLCV":"Yahoo 調整後日線資料", "Yahoo adjusted OHLC contract":"Yahoo Adj Close／原始 Close 比例套用至 OHLC；成交量不調整", "The mega-cap universe is end-of-sample selected and cannot represent general US equities.":"大型科技標的集合以樣本期末存續者選定，不能代表一般美股。",
  "Data center":"資料中心", "Market data, cache and research inputs":"市場資料、本機快取與研究輸入", "System status":"系統狀態", "Frontend":"前端", "Backtest engine":"回測引擎", "Data sources":"資料來源", "Local cache":"本機快取", "Data source status":"資料來源狀態", "Check again":"重新檢查", "Last successful connection":"最後成功連線時間", "Last checked":"最後檢查時間", "Last error type":"最後錯誤類型", "Complete research data":"補齊研究資料", "Risk-free rate":"無風險利率", "Download or update risk-free rate":"下載／更新無風險利率", "Research data progress":"研究資料補齊進度", "Current item":"目前處理", "Completed items":"已完成", "Failed items":"失敗項目", "Continue retrying failed items":"繼續重試失敗項目", "Background jobs":"背景工作", "No background jobs yet.":"目前沒有背景工作。", "View report":"查看報告", "Large-cap technology research group":"大型科技股研究組", "ETF research group":"ETF 研究組", "Complete":"完整", "Incomplete":"未完成", "Updated":"更新時間", "Checking":"檢查中", "normal":"正常", "partial":"部分異常", "not_tested":"尚未測試", "restricted":"受限", "validation_failed":"驗證失敗", "complete":"已完成", "incomplete":"未完成", "not_downloaded":"尚未下載", "available":"已有資料", "The data center is temporarily unavailable.":"資料中心暫時無法載入。", "Unable to start the job.":"目前無法開始工作。", "The service will recover automatically.":"系統會自動嘗試恢復服務。", "Service temporarily unavailable":"服務暫時無法使用",
  "Data connection needs repair":"資料連線需要修復", "Repair data connection":"修復資料連線", "Repairing data connection":"正在修復資料連線", "The system will verify the Windows user service and safely recheck every data source.":"系統會確認 Windows 使用者服務，並安全地重新檢查所有資料來源。", "A one-time Windows confirmation is required to finish the user service setup.":"需要完成一次 Windows 圖形介面確認，才能完成使用者服務設定。", "Double-click the selected setup item in File Explorer, then approve the one-time Windows confirmation.":"請在檔案總管雙擊已選取的設定檔，再於 Windows 一次性確認視窗按「是」。",
  "RESEARCH_MARKET_DATA_DOWNLOAD":"研究市場資料補齊", "RISK_FREE_DATA_DOWNLOAD":"無風險利率下載", "PROVIDER_CONNECTIVITY_CHECK":"資料來源連線檢查", "PROVIDER_CONNECTIVITY_REPAIR":"資料連線修復", "PROVIDER_DOWNLOAD_SMOKE_TEST":"小型真實下載驗證", "RESEARCH_ENVIRONMENT_VALIDATION":"研究環境長期驗證", "QUEUED":"等待中", "PARTIAL_SUCCESS":"部分完成", "FAILED_VALIDATION":"一致性驗證失敗", "CANCELLED":"已取消", "Research jobs":"研究工作", "No research jobs yet.":"目前沒有研究工作。", "Revalidate research environment":"重新驗證研究環境", "Research validation is running":"研究環境驗證執行中", "Research inputs are ready.":"研究輸入已準備完成。", "Complete market data and risk-free data in the Data Center first.":"請先在資料中心補齊市場資料與無風險利率。", "Research environment long-history validation":"研究環境長期驗證",
  "Current research environment snapshot":"本次研究環境快照", "All report sections use this immutable input snapshot":"所有報告區塊皆使用同一份不可變輸入快照", "Snapshot ID":"快照編號", "Created at":"建立時間", "Market data coverage":"市場資料涵蓋", "Validated datasets":"份已驗證資料", "ETF completeness":"ETF 完整度", "Later-listed instruments use real inception-limited history":"較晚上市標的使用實際上市後資料，不補造歷史", "FRED coverage":"FRED 涵蓋期間", "Observations":"筆觀測值", "Previous-known rate, ACT/365, cash balance only":"只使用前期已知利率、ACT/365，且僅現金餘額計息", "Snapshot hash":"快照雜湊", "Market manifest hash":"市場資料清單雜湊", "Risk-free manifest hash":"無風險利率清單雜湊",
  "PROVIDER_CONNECTION_ERROR":"連線失敗", "PROVIDER_TIMEOUT":"連線逾時", "RATE_LIMITED":"下載速度暫時受限", "UPSTREAM_UNAVAILABLE":"資料來源暫時受限", "PROVIDER_VALIDATION_FAILED":"資料驗證失敗", "WINDOWS_LAUNCHER_APPROVAL_REQUIRED":"需要 Windows 一次性確認", "WINDOWS_LAUNCHER_APPROVAL_FAILED":"無法開啟 Windows 確認視窗", "DOWNLOAD_FAILED":"下載失敗", "ADJUSTMENT_BASIS_REVIEW":"價格調整口徑需確認", "JOB_FAILED":"背景工作失敗", "RISK_FREE_DOWNLOAD_FAILED":"無風險利率下載失敗", "RESEARCH_INPUTS_NOT_READY":"研究資料尚未準備完成",
  "advanced_day1_stop":"進階策略＋首日停損", "Advanced + Day1 Stop":"進階策略＋首日停損", "Advanced + Day1 3% Stop":"進階策略＋首日停損",
  "Simple MA Percentage Breakout":"簡易均線百分比突破策略", "Advanced MA Breakout":"進階均線突破策略",
  "Conservative":"保守模式", "Conservative (default)":"保守模式（預設）", "OHLC Heuristic":"OHLC 路徑推估", "Favorable":"有利模式",
  "Intrabar Policy":"日內順序假設", "Daily Intrabar Assumption":"日內順序假設", "Intrabar assumption":"日內順序假設", "Intrabar:":"日內順序：",
  "Market data provider":"市場資料來源", "Provider:":"資料來源：", "Provider":"資料來源", "unknown":"未知", "none":"無",
  "Yahoo + cache + fallback":"Yahoo＋本機快取＋備援", "Yahoo Finance (with fallback)":"Yahoo Finance（含備援）", "Alternative (Stooq)":"替代來源（Stooq）",
  "Auto (cache → Yahoo → Stooq)":"自動（快取 → Yahoo → Stooq）", "auto":"自動", "alternative":"替代來源", "cache":"本機快取", "stale cache":"既有快取",
  "Complete local Parquet cache always wins. Yahoo and Stooq caches are isolated because their adjustment policies may differ.":"完整的本機 Parquet 快取優先使用。Yahoo 與 Stooq 的價格調整方式可能不同，因此各自保存快取。",
  "Daily OHLC does not reveal whether the day's high or low occurred first. This setting controls how ambiguous same-day events are ordered.":"日 K 無法透露最高價與最低價的先後。此設定決定無法辨識順序的事件如何模擬；三種模式都不是實際 tick 路徑。",
  "policy.conservative":"若同一日事件順序無法由日線 OHLC 判定，採對策略較不利的可行順序。這不是實際 tick 路徑。",
  "policy.ohlc_heuristic":"收盤價 ≥ 開盤價：開盤 → 最低 → 最高 → 收盤；收盤價 < 開盤價：開盤 → 最高 → 最低 → 收盤。這是推估，不是實際 tick 路徑。",
  "policy.favorable":"真正存在順序不確定時，採較有利的可行順序。這不是實際 tick 路徑。",
  "ma.help":"MA(t-1) 為前一交易日均線；MA(t) 為當日收盤後完成的均線，盤中不可預先使用。只有跌破保護重置於收盤確認 MA(t)。",
  "Run Backtest":"執行回測", "Run backtest action":"執行回測操作", "Backtest settings":"回測設定", "Strategy Settings":"策略設定", "Research setup":"研究設定", "Active research":"目前研究",
  "Reset parameters":"重設參數", "Market":"市場", "Ticker":"股票代碼", "Start date":"開始日期", "End date":"結束日期", "Use recent test range":"使用近期測試區間",
  "MA type":"均線類型", "MA period":"均線週期", "SMA":"簡單移動平均（SMA）", "EMA":"指數移動平均（EMA）", "MA":"均線",
  "Entry":"進場", "Exit":"出場", "Breakout trigger %":"突破啟動幅度 %", "Entry stop %":"進場門檻幅度 %", "Exit below MA %":"均線下方停損幅度 %",
  "Validation":"確認條件", "Day 1 volume · Day 2 close":"首日成交量・第二日收盤", "Volume increase %":"成交量增幅 %", "Risk Control":"風險控制",
  "Day 1 Stop Below MA %":"首日停損：低於均線 %", "MA risk threshold %":"均線半倉停損幅度 %", "Take Profit":"停利", "First take profit %":"首次停利幅度 %",
  "Extreme Take Profit":"極端停利", "Bias lookback":"乖離回看交易日數", "Bias sigma multiple":"乖離標準差倍數", "ATR period":"ATR 週期", "ATR multiple":"ATR 倍數",
  "Extreme TP % Q0":"極端停利占 Q0 %", "Maximum TP count":"極端停利次數上限", "Minimum position % Q0":"分批停利最低持倉占 Q0 %",
  "Backtest Settings":"回測設定", "Initial capital":"初始資金", "Position size %":"資金配置 %", "Force close at end":"回測結束時全部平倉", "Trading Costs":"交易成本",
  "Commission %":"手續費 %", "Slippage %":"滑價 %", "Long only":"僅做多", "Daily OHLC":"日線 OHLC", "daily_conservative":"日線 OHLC 模擬",
  "Execution Model: Daily OHLC":"成交模型：日線 OHLC", "Execution Model: Daily OHLC — Conservative":"成交模型：日線 OHLC — 保守模式",
  "Backend offline — restart service":"後端離線 — 請重新啟動服務", "Run .\\scripts\\restart-backtest.ps1":"請在電腦執行 .\\scripts\\restart-backtest.ps1",
  "Downloading data…":"正在取得市場資料…", "Preparing indicators…":"正在準備指標…", "Running backtest…":"正在執行回測…", "Calculating results…":"正在計算結果…",
  "Please keep this page open. Duplicate runs are disabled.":"請保持此頁開啟。執行中無法重複送出回測。", "Running the event engine…":"正在執行事件引擎…", "Configure and run your first backtest":"設定參數並開始第一次回測",
  "Daily conditions use completed prior-day MA and ATR values. Daily OHLC execution supports multi-year history and resolves unknowable same-day event order with conservative adverse-first assumptions.":"每日條件使用已完成的前一交易日均線與 ATR。日線 OHLC 支援多年歷史回測；無法辨識的同日事件順序依所選模式模擬，預設採不利事件優先。",
  "Event priority":"事件優先順序", "Adverse-first policy":"不利事件優先", "Reproducible":"結果可重現", "Inspectable":"可逐筆檢視", "Executions & events":"成交與事件",
  "Strategy return":"策略總報酬率", "Buy & hold":"買進持有", "Buy hold":"買進持有", "Total return":"總報酬率", "CAGR":"年化報酬率", "Max drawdown":"最大回撤", "MDD":"最大回撤",
  "Sharpe":"夏普比率", "Sharpe ratio":"夏普比率", "Win rate":"勝率", "Profit factor":"獲利因子", "Final equity":"最終權益", "Alpha vs B&H":"相對買進持有超額報酬",
  "Sortino":"索提諾比率", "Calmar":"卡瑪比率", "Sell executions":"賣出成交次數", "Avg trade return":"平均交易報酬", "Avg holding days":"平均持有天數", "Exposure %":"市場曝險 %",
  "Commission":"手續費", "Slippage":"滑價", "Slippage cost":"滑價成本", "Slippage cost (included)":"滑價成本（已計入價格）", "Equity curve":"權益曲線",
  "Strategy versus buy & hold":"策略與買進持有比較", "Drawdown":"回撤", "Daily equity from running peak":"每日權益相對歷史高點的回撤", "Performance details":"績效詳細資訊", "Monthly returns":"月報酬率",
  "Ambiguous days":"順序不確定交易日", "Ambiguous positions":"含順序不確定事件的交易", "Results tabs":"回測結果分頁", "Legacy strategy version":"舊版策略", "Legacy":"舊版",
  "Position summary":"持倉交易摘要", "Position":"持倉", "Positions":"持倉交易", "Open the backend-recorded daily decision timeline for any completed position":"查看每筆已完成交易由後端記錄的逐日判斷",
  "View Details":"查看詳情", "Execution log":"成交紀錄", "Click a row to focus the stock chart":"點選紀錄以聚焦股票圖表", "Strategy event log":"策略事件紀錄",
  "State transitions, triggers, reference values and ambiguity flags":"狀態轉換、觸發條件、參考值與順序不確定標記", "Submitted parameters":"送出的參數", "Reproducibility record":"重現資訊",
  "Backtest history":"回測歷史紀錄", "Open, delete or clone a saved parameter set":"開啟、刪除或複製已儲存的參數", "No records.":"尚無紀錄。", "No saved backtests yet.":"尚無已儲存的回測。",
  "Details":"詳細資訊", "Record":"紀錄", "Rerun for audit":"請重新回測以建立稽核", "Tap to expand":"點按展開", "View on chart":"在圖表中查看", "Rerun backtest to generate audit":"重新回測以產生稽核資料",
  "Executions CSV":"成交紀錄 CSV", "Positions CSV":"持倉交易 CSV", "Daily equity CSV":"每日權益 CSV", "Event log CSV":"事件紀錄 CSV", "Full JSON":"完整 JSON",
  "Created":"建立日期", "Version":"版本", "Range":"日期區間", "Return":"報酬率", "Status":"狀態", "Actions":"操作", "Open":"開盤價", "High":"最高價", "Low":"最低價", "Close":"收盤價", "Volume":"成交量",
  "action.open":"開啟", "Clone":"複製參數", "Delete":"刪除", "Technical details":"技術詳細資訊", "Backtest could not run":"回測無法執行", "Requested range":"要求區間",
  "Execution model":"成交模型", "Daily bars":"日線筆數", "Provider error":"資料來源錯誤", "Cached coverage":"快取涵蓋區間", "Cache last updated":"快取最後更新", "Data coverage":"資料涵蓋情況",
  "Trade audit":"交易稽核", "Position Inspector":"持倉檢視器", "Position audit inspector":"持倉稽核檢視器", "Close position inspector":"關閉持倉檢視器", "Loading position audit…":"正在載入持倉稽核…",
  "Audit unavailable":"暫時無法取得稽核資料", "Position price path":"持倉價格走勢", "10 trading days before entry through 5 trading days after exit · touch pan and pinch zoom enabled":"進場前 10 個交易日至出場後 5 個交易日・支援觸控平移與雙指縮放",
  "Daily strategy timeline":"逐日策略時間軸", "Backend-recorded states, thresholds, validations and events for every holding day":"每個持有交易日的狀態、門檻、確認條件與事件，皆由後端記錄",
  "Entry date":"進場日期", "Entry price":"進場價格", "Final exit":"最終出場日期", "Final return":"最終報酬率", "Realized PnL":"已實現損益", "Gross PnL":"毛損益", "Net PnL":"淨損益", "Holding days":"持有天數", "Exit reason":"出場原因",
  "Gross PnL uses execution prices and excludes commissions. Realized PnL subtracts all commissions. Slippage is already included in execution prices and is not deducted again.":"毛損益依實際成交價格計算，不扣手續費；已實現損益再扣除所有手續費。滑價已反映在成交價格，不會重複扣除。",
  "Breakout trigger":"突破啟動門檻", "Entry level":"進場門檻", "Day1 Stop":"首日停損", "Simple MA stop":"均線停損線", "MA half stop":"均線下方半倉停損", "BreakDayLow":"跌破保護低點", "BreakDayLow (intraday only)":"跌破保護低點（當日盤中有效）",
  "First TP":"首次停利", "Protective stop":"保護性停損", "Bias extreme":"乖離極端停利", "ATR extreme":"ATR 極端停利", "O":"開", "H":"高", "L":"低", "C":"收", "Vol":"量",
  "BreakDayLow active intraday · Reset after close. This episode’s threshold is inactive after this close; a later half-stop may establish a new episode.":"跌破保護低點於當日盤中有效，收盤後重置。此段保護門檻在該次收盤後停用；未來再次半倉停損時才建立新的保護區段。",
  "Simultaneous conditions:":"可能同時觸發的條件：", "Recorded in event metadata":"詳見事件技術資訊", "Daily market data":"每日市場資料", "Qty open / close":"開盤／收盤股數", "Completed indicators":"已完成的指標",
  "Previous-day MA":"前一交易日均線 MA(t-1)", "Reference MA":"前一交易日均線", "Current-day MA":"當日收盤後完成的均線 MA(t)", "Previous-day ATR":"前一交易日 ATR", "Bias sigma":"乖離標準差",
  "State at open":"開盤狀態", "State at close":"收盤狀態", "Strategy thresholds":"策略門檻", "Entry Zone v2":"進場區間 v2", "LowerEntry":"進場區間下緣", "UpperEntry":"進場區間上緣", "Entry allowed?":"允許進場？", "Entry missed?":"錯過進場？", "Entry execution":"進場成交價格",
  "YES":"是", "NO":"否", "PASS":"通過", "FAIL":"未通過", "Active":"啟用", "Inactive":"未啟用", "Entry Day Volume":"進場日量能確認", "Day 2 Confirmation":"第二日確認",
  "Daily events":"當日事件", "Trigger":"觸發價格", "Execution":"成交價格", "Shares before":"事件前股數", "Shares sold":"賣出股數", "Remaining":"剩餘股數", "No strategy event on this trading day.":"此交易日沒有策略事件。",
  "Stop execution details":"停損成交說明", "Trigger method":"觸發方式", "Intraday stop":"盤中跌破停損線", "Gap-through stop":"跳空跌破停損線", "Active stop":"有效停損線", "Raw fill":"原始成交基準", "Actual execution":"實際成交價", "Sell slippage":"賣出滑價", "Formula":"技術計算式",
  "The open remained above the stop. The intraday low crossed it, so the raw fill is the stop price.":"開盤仍高於停損線，盤中跌破後於停損線觸發。",
  "The open was already at or below the stop, so the open is the raw fill basis.":"開盤已低於或等於停損線，因此以開盤價作為原始成交基準。",
  "Candlestick, volume, reference MA and trade marker chart":"K 線、成交量、前一交易日均線與成交標記圖", "Position candlestick audit chart with MA and strategy thresholds":"持倉 K 線稽核圖：均線與策略門檻", "Chart legend":"圖表圖例",
  "Break low":"跌破保護低點", "Protective":"保護性停損", "Building Day1 Stop diagnostic…":"正在建立首日停損診斷…", "Position-matched diagnostic unavailable":"暫時無法取得配對交易診斷",
  "Entry Zone v2 · six-run sensitivity":"進場區間 v2・六組敏感度比較", "This comparison creates its own Advanced and Day1 Stop runs, so no pre-existing baseline is required.":"此比較會建立進階策略與首日停損策略的回測，不需要事先存在的基準結果。",
  "Run six backtests":"執行六組回測", "Day1 full stops":"首日全數停損次數", "OHLC ambiguity":"OHLC 順序不確定", "Unambiguous":"順序可判定", "Matched to Advanced":"與進階策略配對數",
  "Daily Intrabar Assumption Sensitivity":"日內順序假設敏感度分析", "Runs the same ticker, dates, costs and strategy parameters under Conservative, OHLC Heuristic, and Favorable ordering. The heuristic is an assumption, not a real intraday path.":"以相同股票、日期、成本與策略參數比較保守模式、OHLC 路徑推估與有利模式。推估只是假設，不是實際日內路徑。",
  "Run Ambiguity Sensitivity":"執行順序假設敏感度分析", "Backtest-level comparison":"整體回測比較", "Same inputs and shared Advanced parameters; only the Day 1 full stop differs.":"使用相同輸入與進階策略共同參數，唯一差異是首日全數停損。",
  "Existing Advanced":"現行進階策略", "Return difference":"報酬率差異", "Final equity difference":"最終權益差異", "Matched divergences":"配對後路徑差異數", "Ambiguity cohorts":"順序不確定分組",
  "Forward returns use the selected trading-day close versus the actual stop execution price.":"後續報酬以指定交易日收盤價相對實際停損成交價計算。", "Unambiguous Day1 Stops":"順序可判定的首日停損", "DAILY_INTRABAR_AMBIGUITY Stops":"含日內順序不確定的停損",
  "Every DAY1_FULL_STOP":"所有首日全數停損", "Prev MA":"前一交易日均線", "Stop":"停損價", "O / H / L / C":"開／高／低／收", "Loss":"損失", "Ambiguity":"順序不確定", "Next":"次日", "5D":"5 個交易日", "10D":"10 個交易日", "20D":"20 個交易日",
  "Largest return damage":"報酬損害最大交易", "Largest improvements":"改善最大交易", "All path divergences":"所有路徑差異", "Count":"次數", "Average stop loss":"平均停損損失", "Median 5D":"5 日報酬中位數", "Median 10D":"10 日報酬中位數", "Median 20D":"20 日報酬中位數",
  "Variant PnL minus the matching Existing Advanced position PnL.":"變體損益減去配對的現行進階策略交易損益。", "Original Advanced outcome":"原進階策略結果", "Day1 Stop outcome":"首日停損策略結果", "PnL difference":"損益差異", "Inspect":"檢視", "Day1":"首日",
  "Advanced and Advanced + Day1 Stop use identical Entry Zone v2 semantics. Only ambiguous Daily OHLC ordering changes by policy.":"進階策略與進階策略＋首日停損採相同的 v2 進場區間規則。模式只用於日線 OHLC 事件順序假設。",
  "Policy":"順序模式", "Day1 stops":"首日停損", "Same-policy matched delta":"相同模式下的配對差異", "Advanced + Day1 Stop minus Existing Advanced; positions are matched by entry date.":"首日停損策略減去現行進階策略；交易依進場日期配對。",
  "Matched":"已配對", "Advanced only":"僅進階策略", "Day1 only":"僅首日停損策略", "Matched PnL delta":"配對損益差異", "Total return delta":"總報酬率差異", "Inspect runs":"查看回測", "Use History IDs":"依歷史回測編號查看", "Legacy chased entries":"舊版追價進場", "unavailable":"無法取得", "Date":"日期", "Gap above":"開盤超過上緣幅度",
  "Jan":"1 月", "Feb":"2 月", "Mar":"3 月", "Apr":"4 月", "May":"5 月", "Jun":"6 月", "Jul":"7 月", "Aug":"8 月", "Sep":"9 月", "Oct":"10 月", "Nov":"11 月", "Dec":"12 月",
  "FLAT":"空手", "ENTRY_ARMED":"進場已啟動", "LONG_VALIDATING_DAY1":"持有中・首日待確認", "LONG_VALIDATING_DAY2":"持有中・第二日待確認", "LONG_NORMAL":"正常持有", "BREAK_PROTECTION":"跌破保護", "POST_FIRST_TP":"首次停利後", "PENDING_FULL_EXIT_NEXT_OPEN":"等待次日開盤全數出場", "CLOSED":"已平倉",
  "BUY":"買進", "SELL":"賣出", "ENTRY":"進場", "ENTRY_LEVEL":"進場門檻", "ENTRY_STOP_FILLED":"進場委託成交", "BREAKOUT_TRIGGERED":"突破條件已啟動", "ENTRY_ZONE_MISSED":"錯過進場區間", "GAP_ABOVE_ENTRY_ZONE":"開盤跳空超過進場區間",
  "FIRST_TP_TRIGGERED":"首次停利觸發", "FIRST_TAKE_PROFIT":"首次停利", "FIRST_TP":"首次停利", "EXTREME_TP":"極端停利", "EXTREME_TP_EXECUTED":"極端停利成交",
  "MA_BREAK_HALF_EXIT":"均線下方半倉停損", "MA_HALF_EXIT":"均線下方半倉停損", "MA_HALF_STOP":"均線下方半倉停損", "MA_EXIT":"均線下方停損線全數出場", "BREAK_HALF_TRIGGERED":"均線下方半倉停損觸發", "BREAK_PROTECTION_STARTED":"跌破保護開始", "BREAK_PROTECTION_RESET":"跌破保護重置", "BREAK_DAY_LOW":"跌破保護低點", "BREAK_DAY_LOW_BROKEN":"跌破保護低點失守", "BREAK_LOW_BROKEN":"跌破保護低點失守", "BREAK_LOW_EXIT":"跌破保護全數出場",
  "PROTECTIVE_STOP":"保護性停損", "PROTECTIVE_STOP_TRIGGERED":"保護性停損觸發", "DAY1_FULL_STOP":"首日全數停損", "END_OF_BACKTEST":"回測結束平倉", "FINAL_EXIT":"全數出場",
  "VOLUME_CONFIRMATION_PASS":"量能確認通過", "VOLUME_CONFIRMATION_FAIL":"量能確認失敗", "DAY2_CONFIRMATION_PASS":"第二日確認通過", "DAY2_CONFIRMATION_FAIL":"第二日確認失敗", "DAY2_CLOSE_CONFIRMATION_FAIL":"第二日收盤確認失敗",
  "BIAS_EXTREME_ENTER":"乖離極端條件啟動", "BIAS_EXTREME_EXIT":"乖離極端條件解除", "ATR_EXTREME_ENTER":"ATR 極端條件啟動", "ATR_EXTREME_EXIT":"ATR 極端條件解除", "BIAS_EXTREME":"乖離極端停利", "ATR_EXTREME":"ATR 極端停利", "BIAS+ATR_EXTREME":"乖離與 ATR 同時極端停利",
  "PARTIAL_TP_BLOCKED_MIN_POSITION":"持倉低於門檻，禁止分批停利", "DAILY_INTRABAR_AMBIGUITY":"日線 OHLC 事件順序不確定", "INTRABAR_RANGE":"日內價格區間階段", "INTRADAY_RANGE":"日內價格區間階段", "OPEN phase":"開盤階段", "CLOSE phase":"收盤確認",
  "COMPLETED":"已完成", "SUCCESS":"已完成", "RUNNING":"執行中", "PENDING":"等待中", "FAILED":"失敗", "online":"可連線", "degraded":"部分可用", "offline":"離線",
  "MATCHED":"已配對", "UNMATCHED":"無對應交易", "NO_MATCHING_ENTRY":"無相同進場交易",
  "Daily candles · volume · previous-day reference MA · execution markers":"日 K・成交量・前一交易日均線・成交標記", "Yahoo:":"Yahoo：",
  "Quantity":"股數", "Qty":"股數", "trading days":"個交易日", "MA(t-1)":"前一交易日均線", "MA(t)":"當日收盤後完成的均線",
  "Daily OHLC ambiguity — adverse-first assumption applied":"日線 OHLC 事件順序不確定 — 已採不利事件優先假設",
  "adjusted_for_splits":"已調整拆股價格", "split_adjusted":"已調整拆股價格", "cache-first":"優先使用快取", "ok":"正常",
  "Page not found":"找不到此頁面", "The requested page does not exist.":"指定的頁面不存在。", "Back to dashboard":"返回回測總覽", "The page could not load":"暫時無法載入頁面", "Your saved backtests are unchanged. Please try again.":"已儲存的回測不受影響，請再試一次。", "Retry":"重試",
};

const fields: Record<string,string> = {
  position_id:"交易編號", timestamp:"日期", side:"買賣方向", price:"價格", quantity:"股數", gross_value:"成交總額", position_remaining:"剩餘股數", event_type:"事件類型", reason:"原因", event:"事件", metadata:"技術資料",
  entry_date:"進場日期", final_exit_date:"最終出場日期", entry_price:"進場價格", exit_price:"出場價格", initial_shares:"初始股數 Q0", total_shares_sold:"累計賣出股數", final_return:"最終報酬率", return_pct:"報酬率", q0:"初始股數 Q0", fees:"手續費",
  maximum_favorable_excursion:"最大有利價格變動", maximum_adverse_excursion:"最大不利價格變動", exit_final_close_reason:"最終出場原因", current_qty:"目前股數", realized_pnl:"已實現損益", unrealized_pnl:"未實現損益",
  daily_reference_ma:"前一交易日均線", trigger_price:"觸發價格", current_price:"當時價格", position_before:"事件前股數", position_after:"事件後股數", state_before:"事件前狀態", state_after:"事件後狀態",
  daily_bars_count:"日線筆數", warmup_bars_count:"暖機資料筆數", warm_up_bars:"暖機資料筆數", warmup_bars:"暖機資料筆數", first_strategy_date:"第一個策略交易日", last_strategy_date:"最後一個策略交易日", missing_trading_days:"缺少的交易日", data_provider:"資料來源", provider_display_name:"資料來源", cache_last_updated:"快取最後更新", cache_coverage:"快取涵蓋區間", data_source:"資料取得方式",
  ma_type:"均線類型", ma_period:"均線週期", breakout_trigger_pct:"突破啟動幅度 %", entry_stop_pct:"進場門檻幅度 %", exit_below_ma_pct:"均線下方停損幅度 %", volume_increase_pct:"成交量增幅 %", ma_risk_pct:"均線半倉停損幅度 %", first_tp_pct:"首次停利幅度 %", bias_lookback:"乖離回看交易日數", bias_sigma_multiple:"乖離標準差倍數", atr_period:"ATR 週期", atr_multiple:"ATR 倍數", extreme_tp_pct_q0:"極端停利占 Q0 %", max_extreme_tp_count:"極端停利次數上限", minimum_position_pct_q0:"分批停利最低持倉占 Q0 %", day1_stop_pct:"首日停損低於均線 %", position_size_pct:"資金配置 %", execution_policy:"日內順序假設", force_close_at_end:"期末全數平倉",
  current_volume:"當日成交量", previous_day_volume:"前一交易日成交量", increase_pct:"成交量增幅 %", required_pct:"要求增幅 %", required_volume:"要求成交量", day1_close:"首日收盤價", day2_close:"第二日收盤價", current_quantity_at_open:"開盤股數", current_quantity_at_close:"收盤股數", entry_day_volume:"進場日成交量",
  total_return:"總報酬率", buy_hold_return:"買進持有報酬率", alpha_vs_buy_hold:"相對買進持有超額報酬", max_drawdown_start:"最大回撤開始日", max_drawdown_bottom:"最大回撤谷底日", recovery_date:"回復高點日期", number_of_positions:"交易筆數", number_of_sell_executions:"賣出成交次數", average_trade_return:"平均交易報酬", median_trade_return:"交易報酬中位數", average_winner:"平均獲利交易損益", average_loser:"平均虧損交易損益", best_trade:"最佳交易損益", worst_trade:"最差交易損益", average_holding_days:"平均持有天數", exposure_pct:"市場曝險 %", total_commission:"總手續費", estimated_slippage_cost:"估計滑價成本", sortino_ratio:"索提諾比率", calmar_ratio:"卡瑪比率",
};
Object.assign(zhTW, fields);
Object.assign(zhTW, {
  strategy_parameters:"策略參數", code_version:"程式版本", strategy_version:"策略版本", daily_first_timestamp:"日線資料起始日期", daily_last_timestamp:"日線資料結束日期", data_fetch:"資料取得紀錄", adjustment_mode:"價格調整方式", requested_start:"要求開始日期", requested_end:"要求結束日期", cache_available:"快取是否可用", cache_complete:"快取是否完整", cache_metadata:"快取資訊", yahoo_error:"Yahoo 錯誤", provider_error_code:"資料來源錯誤代碼", yahoo_hosts_attempted:"已嘗試的 Yahoo 主機", cache_validation:"快取驗證", selected_provider:"使用的資料來源", provider_selection:"資料來源選擇方式", provider_attempts:"資料來源嘗試紀錄", start:"開始日期", end:"結束日期", bars:"資料筆數", last_updated:"最後更新時間", complete:"是否完整", missing_ranges:"缺少的區間", first_date:"第一日", last_date:"最後一日", source:"來源", day1_volume:"首日成交量", previous_volume:"前日成交量", volume_increase_pct_actual:"實際成交量增幅 %", threshold_pct:"要求幅度 %", phase:"事件階段",
});
const normalize = (key: string) => key.trim().toLowerCase().replaceAll("_", " ");
const index = new Map(Object.entries(zhTW).map(([k,v]) => [normalize(k),v]));
export function t(key: unknown): string {
  if (key == null) return "—";
  const raw = String(key);
  return zhTW[raw] ?? index.get(normalize(raw)) ?? raw;
}
export function hasTranslation(key: string): boolean { return index.has(normalize(key)); }
export const money = (v: unknown) => v == null || !Number.isFinite(Number(v)) ? "—" : `$${Number(v).toLocaleString(locale,{minimumFractionDigits:2, maximumFractionDigits:2})}`;
export const num = (v: unknown, digits=2) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString(locale,{maximumFractionDigits:digits});
export const shares = (v: unknown) => v == null ? "—" : `${num(v,0)} 股`;
export const dateText = (v: unknown) => v ? String(v).slice(0,10) : "—";
export function displayValue(key: string, v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? t("YES") : t("NO");
  if (Array.isArray(v)) return v.length ? v.map(x=>displayValue("",x)).join("；") : t("none");
  if (typeof v === "object") return Object.entries(v).map(([k,x])=>`${t(k)}：${displayValue(k,x)}`).join("；");
  if (key === "phase") return t(`${v} phase`);
  if (/date|timestamp|created_at/.test(key)) return dateText(v);
  if (typeof v === "number") {
    if (/price|pnl|fees|commission|slippage|gross_value|capital|equity/.test(key)) return money(v);
    if (/shares|quantity|qty|q0|position_(before|after|remaining)/.test(key)) return shares(v);
    if (/pct|return/.test(key)) return `${v.toFixed(2)}%`;
    return num(v,4);
  }
  return t(v);
}

export const errorLabels: Record<string,string> = {
  NO_DATA:"指定區間沒有日線歷史資料", NO_HISTORICAL_DATA:"指定區間沒有日線歷史資料", NO_DAILY_BARS:"指定區間沒有可用日線資料", INVALID_TICKER:"股票代碼無效",
  PROVIDER_CONNECTION_ERROR:"市場資料來源目前無法連線", PROVIDER_TIMEOUT:"市場資料來源回應逾時", RATE_LIMITED:"市場資料來源暫時限制請求次數", CACHE_INCOMPLETE:"快取涵蓋不完整，且無法取得缺少的資料", MARKET_DATA_PROVIDERS_UNAVAILABLE:"市場資料來源目前無法補齊缺少的日線資料",
  BACKEND_UNAVAILABLE:"後端服務目前無法連線，請在電腦重新啟動服務", PROVIDER_UNAVAILABLE:"市場資料來源目前無法使用", MARKET_DATA_UNAVAILABLE:"市場資料來源目前無法使用",
  INVALID_REQUEST:"請檢查股票、日期與策略參數", VALIDATION_ERROR:"參數驗證未通過", DATA_TIMEZONE_MISMATCH:"資料時區不一致", INVALID_DATA_SCHEMA:"市場資料格式不正確",
  NOT_ENOUGH_MA_LOOKBACK:"均線暖機資料不足", NOT_ENOUGH_BIAS_HISTORY:"乖離標準差歷史資料不足", NOT_ENOUGH_ATR_HISTORY:"ATR 暖機資料不足", NOT_FOUND:"找不到指定的回測紀錄",
  POSITION_AUDIT_NOT_FOUND:"此回測沒有持倉稽核資料；舊版回測需重新執行才能產生稽核", MATCHING_BASELINE_REQUIRED:"請先以相同股票、日期、成本與參數執行進階策略，建立配對基準",
  BASELINE_NOT_FOUND:"找不到指定的進階策略基準", BASELINE_PARAMETERS_MISMATCH:"配對基準的股票、日期、成本或參數不同", INVALID_DIAGNOSTIC_SOURCE:"請先完成進階策略＋首日停損回測", INVALID_SENSITIVITY_SOURCE:"請先完成進階策略＋首日停損回測",
};
export function errorText(message: string, code?: string): string {
  if (code && errorLabels[code]) return errorLabels[code];
  if (hasTranslation(message)) return t(message);
  if (/backend offline|failed to fetch|network/i.test(message)) return errorLabels.BACKEND_UNAVAILABLE;
  if (/baseline|same ticker/i.test(message)) return errorLabels.MATCHING_BASELINE_REQUIRED;
  if (/unavailable|could not be reached|connection/i.test(message)) return errorLabels.PROVIDER_UNAVAILABLE;
  if (/history|lookback/i.test(message) && /not enough/i.test(message)) return "已完成的指標歷史資料不足";
  if (/no .*historical|no daily/i.test(message)) return errorLabels.NO_DATA;
  return "無法完成此操作，請查看技術詳細資訊。";
}
export function warningText(message: string | null): string {
  message = message ?? "";
  if (hasTranslation(message)) return t(message);
  if (/No trades generated/i.test(message)) return "此區間未產生交易";
  if (/Yahoo currently unavailable.*cached/i.test(message)) return "Yahoo 目前無法連線 — 使用本機快取的市場資料。";
  if (/Yahoo currently unavailable.*Stooq/i.test(message)) return "Yahoo 目前無法連線，已自動改用 Stooq 日線資料。";
  if (/cached.*Yahoo|Yahoo.*cache/i.test(message)) return "使用本機快取的 Yahoo 日線資料。";
  if (/Stooq.*cache|cached.*Stooq/i.test(message)) return "使用本機快取的 Stooq 日線資料。";
  if (/cache/i.test(message)) return "使用本機快取市場資料；涵蓋範圍與最後更新時間請見資料涵蓋情況。";
  if (/ambiguity.*adverse.first/i.test(message)) return t("Daily OHLC ambiguity — adverse-first assumption applied");
  if (/daily OHLC|daily.*path|adverse.first|heuristic/i.test(message)) return "本回測使用日線 OHLC。同日事件順序無法判定時，依所選日內順序模式模擬；這不是實際 tick 路徑。";
  if (/missing|incomplete/i.test(message)) return "市場資料有缺漏，請查看資料涵蓋情況與技術詳細資訊。";
  if (/split|adjust|dividend/i.test(message)) return "資料涉及拆股或股息調整假設，請查看技術詳細資訊。";
  return "市場資料或模擬假設提示：請查看技術詳細資訊。";
}

export const messages = {
  entryHint:(arm:number,buy:number)=>`啟動 +${arm}%・進場 +${buy}%`,
  riskHint:(day1:number,risk:number)=>`首日 −${day1}%・第二日起 −${risk}%`,
  firstHint:(pct:number)=>`首次停利 +${pct}%`,
  tradingDays:(count:number)=>`${num(count,0)} 個交易日`,
  events:(count:number)=>`${num(count,0)} 個事件`,
  quantityChange:(before:number,after:number)=>`${shares(before)} → ${shares(after)}`,
  strategyVersion:(v:number)=>`策略版本 ${v}`,
  priceExecutions:(ticker:string)=>`${ticker} 價格與成交`,
  sensitivityTitle:(v:number)=>`策略版本 ${v}・2 × 3 模式矩陣`,
  allDivergences:(n:number)=>`所有路徑差異（${n}）`,
  legacyEntries:(n:number|string)=>`舊版追價進場（${n}）`,
  simpleMaStopLine:(pct:number)=>`均線 −${num(pct,2)}% 停損線`,
  simpleMaStopExit:(pct:number)=>`均線 −${num(pct,2)}% 停損出場`,
  maHalfStopLine:(pct:number)=>`均線 −${num(pct,2)}% 半倉停損`,
  maStopHelp:(pct:number,multiplier:number)=>`此門檻使用前一交易日均線計算：前一交易日均線 × ${num(multiplier * 100,2)}%（低於均線 ${num(pct,2)}%）。`,
};
