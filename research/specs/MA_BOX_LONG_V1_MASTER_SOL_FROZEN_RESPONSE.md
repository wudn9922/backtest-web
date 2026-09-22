# MA_BOX_LONG_V1 MASTER SPEC

## 決策摘要

- Repo 中只找到一套 authoritative normal-entry semantics，沒有互相衝突的版本。
- Canonical MA stop、OHLC Heuristic、commission、slippage 可以直接重用。
- `MA_BOX_LONG_V1` 將使用獨立 namespace、資料表、結果 revision 與前端頁面。
- Simple v2、Advanced v2、Advanced + Day1Stop、既有 cache 和歷史結果都不修改。
- 所有會影響結果的狀態轉移、箱型邊界、風險距離、retest 與 breakout timeout 已在本規格中明確凍結。
- 本輪沒有修改程式，也沒有啟動 Luna。

---

## 1. Repo current-state audit

目前正式引擎已有可重用元件：

- SMA 與 `MA(t-1)` 計算
- Normal Entry Zone
- `ENTRY_ZONE_MISSED`
- Canonical MA stop
- Gap-through stop fill
- OHLC Heuristic 日內順序
- Portfolio sizing
- Commission/slippage accounting
- Forced end-of-test exit
- Position、execution、event、equity audit
- 既有績效指標

目前 legacy strategy enum 只有：

- Simple
- Advanced
- Advanced + Day1Stop

決策：

`MA_BOX_LONG_V1` 不直接塞進舊 strategy selector。建立獨立研究／比較入口，避免舊結果被重新解讀或污染。

---

## 2. Authoritative normal-entry semantics

Repo 只有一套正式定義：

```text
LowerEntry = MA(t-1) × 1.01
UpperEntry = MA(t-1) × 1.015
```

### Arm

當日：

```text
Open >= LowerEntry
或
High >= LowerEntry
```

即 entry armed。

### Fill

當日：

```text
High >= UpperEntry
```

才可成交。

正常 raw fill：

```text
UpperEntry
```

### Gap / no-chase

若：

```text
Open > UpperEntry
```

整日標記：

```text
ENTRY_ZONE_MISSED
```

即使之後價格跌回 Entry Zone，也不追價。

`Open == UpperEntry` 可正常成交。

### Session semantics

Normal entry 是使用 `MA(t-1)` 的當日 stop-entry：

- 不需要等待當日收盤確認
- armed 狀態只在當日有效
- 不跨 session 延續
- 未成交則當日結束失效

### Buy execution

```text
actual buy price
= raw fill × (1 + 0.02%)
```

依可用現金與 commission 計算整股數量。

這套 semantics 同時存在於 Simple、Advanced 和 Advanced + Day1Stop，沒有第二個相衝突版本。

---

## 3. Authoritative stop and cost semantics

### MA stop

```text
Stop(t) = MA(t-1) × 0.985
```

### Intraday touch

若：

```text
Open > Stop
Low <= Stop
```

則：

```text
raw sell fill = Stop
```

### Gap-through

若：

```text
Open <= Stop
```

則：

```text
raw sell fill = Open
```

### Sell slippage

```text
actual sell price
= raw sell fill × (1 - 0.02%)
```

### Frozen V1 costs

```text
Initial capital: 100,000
Position size: 100%
Commission: 0.05% per transaction
Slippage: 0.02% per transaction
Force close at study end: true
```

Commission 以實際成交金額計算。

`MA_BOX_LONG_V1` 不建立另一套 stop、portfolio 或成本引擎。

---

## 4. Exact strategy scope

V1 固定：

```text
Strategy revision: MA_BOX_LONG_V1
Direction: Long only
Bars: Daily
MA type: SMA only
Profit target: None
Partial exit: None
Short selling: None
Primary exit: MA(t-1) × 0.985
Execution policy: OHLC_HEURISTIC
```

使用者可以輸入：

- Ticker
- Selected SMA
- Nearby range
- Step
- Start date
- End date

Defaults：

```text
Nearby range: ±5
Step: 1
```

不提供：

- MA ranking
- optimizer
- automatic best-MA selection
- composite score

---

## 5. State-machine architecture

Box setup 與持倉必須是兩個正交 state。

### Position state

```text
FLAT
LONG_POSITION
```

### Setup state

```text
TREND_ELIGIBLE
BOX_FORMING
BOX_ACTIVE
BREAKOUT_CONFIRMED
DIRECT_ENTRY_ELIGIBLE
WAIT_RETEST
RETEST_CONFIRMED
FAILED_BREAKOUT
BEAR_BOX_BREAK
BOX_INVALIDATED
```

因此可以合法存在：

```text
LONG_POSITION + BOX_ACTIVE
```

Box 形成不會平掉既有 position。

### 核心轉移

| Current | Condition | Next |
|---|---|---|
| TREND_ELIGIBLE | Entanglement 於 close 確認 | BOX_FORMING |
| BOX_FORMING | 建立初始邊界 | BOX_ACTIVE |
| BOX_ACTIVE | Close > pre-close BoxHigh | BREAKOUT_CONFIRMED |
| BREAKOUT_CONFIRMED | Close-based indicative risk ≤5% | DIRECT_ENTRY_ELIGIBLE |
| BREAKOUT_CONFIRMED | Indicative risk >5% | WAIT_RETEST |
| DIRECT_ENTRY_ELIGIBLE | Next-open actual risk ≤5% | LONG_POSITION |
| DIRECT_ENTRY_ELIGIBLE | Next-open gap risk >5% | WAIT_RETEST |
| WAIT_RETEST | Valid retest close | RETEST_CONFIRMED |
| RETEST_CONFIRMED | Next-open actual risk ≤5% | LONG_POSITION |
| RETEST_CONFIRMED | Next-open risk >5% | WAIT_RETEST |
| WAIT_RETEST | Failed-break condition | FAILED_BREAKOUT |
| FAILED_BREAKOUT | Reactivate same historical box | BOX_ACTIVE |
| BOX_ACTIVE/WAIT_RETEST | Close < BoxLow | BEAR_BOX_BREAK |
| BEAR_BOX_BREAK | No short; archive box | BOX_INVALIDATED |
| LONG_POSITION | Canonical MA stop | FLAT |
| Any open position | Study end | FORCED_END_OF_TEST_EXIT |

### Forbidden transitions

- BOX_ACTIVE → NORMAL_MA_ENTRY
- BOX formation → automatic exit
- Breakout close → same-day entry
- Retest close → same-day low/MA fill
- Downward box break → short entry
- +3%、+5%、+10% → profit exit
- Failed attempt → reuse old attempt ID

---

## 6. No-lookahead timing table

| Observation | Known | Earliest action |
|---|---|---|
| Normal Entry Zone using MA(t-1) | Session t intraday | Session t canonical stop-entry |
| Entanglement using MA(t) | After t close | State active from t+1 |
| Boundary update | After t close | New boundary effective t+1 |
| Box breakout | After t close | Earliest t+1 open |
| Retest rebound | After t close | Earliest t+1 open |
| Failed breakout | After t close | Reactivated state from t+1 |
| Down box break | After t close | Invalidated state from t+1 |
| MA stop | During t, using MA(t-1) | Session t canonical fill |
| Forced exit | Final session close | Final close execution |

Normal entry is not a completed-close signal. Box detection、breakout 和 retest 是 completed-close signals。

---

## 7. Frozen entanglement definition

在 completed day `t`，檢查恰好最近四個 trading bars：

```text
t-3, t-2, t-1, t
```

每根使用自己的 completed `SMA(t)`。

### Candle crosses MA

```text
Low(i) <= SMA(i) <= High(i)
```

四天中至少三天成立。

### Close-side requirement

只看 qualifying candles：

- 至少一根 `Close > SMA`
- 至少一根 `Close < SMA`
- 依時間排列的非 neutral sides 至少有一次 side switch

`Close == SMA` 為 neutral，不提供上／下側證據。

三根都只收在同一側，不形成 Box。

### Box creation

條件首次於 t close 成立：

1. `MA_ENTANGLEMENT_START`
2. `BOX_FORMING`
3. 建立 box
4. `BOX_ACTIVE` 自 t+1 起生效

初始範圍使用完整四根 bars：

```text
BoxHigh_initial = max(High of four bars)
BoxLow_initial  = min(Low of four bars)
```

不回頭取消 t 日或更早已發生的交易。

---

## 8. Boundary tolerance decision

三種架構比較：

| Mode | 優點 | 主要問題 |
|---|---|---|
| FIXED_PERCENT | 簡單 | 對不同價格與波動股票偏誤大 |
| RECENT_RANGE_NORMALIZED | 可適應近期 range | 容易受 gap、單一極端 bar 和 lookback 選擇影響 |
| ATR_NORMALIZED | 跨價格尺度較穩定；專案已有正式 ATR | 波動突然擴張時 tolerance 可能漂移 |

### V1 frozen choice

```text
boundary_contact_tolerance_mode = ATR_NORMALIZED
ATR period = 14
Tolerance = 0.10 × ATR14(box creation day)
```

ATR 使用 completed day 的正式 Wilder ATR。

Tolerance 在 box 建立時凍結，該 box 整個 lifecycle 不再跟著 ATR 漂移。

如果 ATR 不存在、非 finite 或不大於零：

```text
BOX_FORMING_NOT_READY_ATR
```

不得建立 box。

其他 tolerance modes 只保留介面能力，不在 V1 啟用。

---

## 9. Boundary clustering and update rule

### Contact pool

每個 point 權重均為 1：

```text
Open
High
Low
Close
```

初始四根 bars 全部加入。

BOX_ACTIVE 期間，尚未 breakout/down-break 的每根 completed bar 亦加入。

### Upper/lower separation

以初始 box midpoint：

```text
Mid = (BoxHigh_initial + BoxLow_initial) / 2
```

凍結分區：

- Upper candidates：price ≥ Mid
- Lower candidates：price ≤ Mid

避免 BoxHigh、BoxLow 同時被中間同一群 contacts 吸走。

### Candidate clustering

對每個 contact price 作 seed：

1. 收集距 seed 不超過 tolerance 的同側 points
2. 以這些 points 的 median 作 candidate level
3. 再以 candidate level 重算一次 contacts
4. 記錄 contact count、distinct bars、MAD

候選至少要涵蓋兩個不同 trading bars。

### 更新門檻

新 candidate 的 contact count 必須嚴格高於現有 boundary 的 supporting contact count，才可更新。

Contact 數相同時，不更新 boundary。

這避免每天因微小價格差異漂移。

### Candidate tie-break

在多個同樣最高 contact-count 的新候選中：

1. distinct trading bars 較多
2. MAD 較小
3. 距現有 boundary 較近
4. 最終 deterministic fallback：
   - BoxHigh 選較高值
   - BoxLow 選較低值

最後 fallback 採保守、較寬的箱型。

### Daily evaluation order

使用當日開始前已知的 boundaries：

1. 判斷 upward breakout
2. 判斷 downward break
3. 兩者皆否，才把 completed t bar 加入 contacts
4. 收盤後更新 boundary
5. 新 boundary 從 t+1 生效

Breakout bar 不得先把 BoxHigh 向上移，再宣稱沒有突破。

每次更新保留：

- date
- old/new boundary
- tolerance
- contacts
- distinct bars
- supporting OHLC points
- reason

---

## 10. Breakout and 5% risk-distance logic

### Upward breakout

```text
Close(t) > BoxHigh(t)
```

BoxHigh 使用 t session 開始前已知值。

Breakout attempt 取得新的 immutable attempt ID。

### Indicative close-based gate

t close 後先計算：

```text
IndicativeEntry
= Close(t) × (1 + slippage)

NextSessionStop
= SMA(t) × 0.985

IndicativeRisk
= (IndicativeEntry - NextSessionStop) / IndicativeEntry
```

若：

```text
0 < IndicativeRisk <= 5%
```

則進入 `DIRECT_ENTRY_ELIGIBLE`。

否則：

```text
NO_ENTRY_RISK_DISTANCE_GT_5
WAIT_RETEST
```

### Actual next-open gate

t+1：

```text
ActualEntry = Open(t+1) × (1 + slippage)
Stop        = SMA(t) × 0.985
ActualRisk  = (ActualEntry - Stop) / ActualEntry
```

允許 direct entry 必須：

```text
ActualEntry > Stop
ActualRisk <= 5%
```

若 gap 造成超過 5%：

```text
NO_ENTRY_GAP_RISK_GT_5
WAIT_RETEST
```

若 ActualEntry 不高於 stop：

```text
NO_ENTRY_OPEN_AT_OR_BELOW_STOP
WAIT_RETEST
```

Commission 不放入 risk-distance 分子；slippage 後實際買價要放入。

已確認 breakout 後，next open 不要求仍高於 BoxHigh。Box failure 只由 completed close 判斷，不用 opening gap 回溯否定前一日 breakout。

---

## 11. Retest logic

只適用於已確認 breakout 的 `WAIT_RETEST`。

Completed day t：

```text
Low(t) <= SMA(t)
AND
Close(t) > SMA(t)
```

則：

```text
MA_RETEST_TOUCH
MA_RETEST_REBOUND
RETEST_CONFIRMED
```

不能成交於：

- t 日 Low
- t 日 SMA
- t 日 Close

最早 t+1 open。

t+1 entry 使用 Open、buy slippage 和相同 5% risk gate。

Risk 超過 5% 時維持 `WAIT_RETEST`，不追價。

### Frozen retest precedence

WAIT_RETEST 收盤處理順序：

1. `Close < BoxLow`：BEAR_BOX_BREAK
2. Valid retest：RETEST_CONFIRMED
3. 非 retest 且 `Close <= BoxHigh`：FAILED_BOX_BREAKOUT
4. Timeout
5. 繼續 WAIT_RETEST

因此，一根合法碰 MA 並收回 MA 上方的 retest bar，即使仍位於舊 BoxHigh 下方，也優先視為 retest，而不是 failed breakout。

---

## 12. Failed breakout and invalidation

### Failed breakout

在 WAIT_RETEST 中：

```text
Close <= BoxHigh
```

且該日不符合 valid retest，標記：

```text
FAILED_BOX_BREAKOUT
BOX_REACTIVATED
```

同一 close 重新回到 `BOX_ACTIVE`。

- 保留原 box ID
- 關閉本次 attempt ID
- 下次突破建立新 attempt ID
- failed bar 可加入 contact pool
- boundary refinement 最早於下一個 completed close 生效

### Attempt lifetime

凍結：

```text
breakout_attempt_max_sessions = 20
```

Breakout 後第一個 trading day 算第 1 日。

第 20 個後續 completed session 結束仍未 entry、未 failed、未 down-break：

```text
BOX_INVALIDATED
reason = RETEST_WAIT_EXPIRED
```

不得延續數十天。

### Downward break

```text
Close < BoxLow
```

Flat：

- `BEAR_BOX_BREAK`
- 不開 short
- `BOX_INVALIDATED`

Long：

- 記錄 BEAR_BOX_BREAK
- 不建立 box stop
- position 仍只由 canonical MA stop 管理
- box overlay invalidated

### Box rearm after invalidation

新 box 必須由 invalidation 後四根新的 completed bars 重新滿足 entanglement。

不得重用舊 box 的三根 bars 立即重建。

### Entry consumes box

Direct/retest entry 成功後：

- position → LONG_POSITION
- box 標記 `BOX_INVALIDATED`
- invalidation reason：`BOX_CONSUMED_BY_ENTRY`

Box 不再追著已持有 position 更新。

---

## 13. MA_LONG_BASELINE and Buy & Hold

每個 period 同時產生：

### A. MA_LONG_BASELINE

- Authoritative Normal Entry Zone
- Canonical MA−1.5% stop
- OHLC Heuristic
- 相同成本
- 無 Box、entanglement、breakout/retest filter

### B. MA_BOX_LONG_V1

增加本規格的 box state machine。

### C. BUY_AND_HOLD

整個 study 共用一條 B&H：

- common evaluation start 第一個 session Open 買入
- 100% capital、整股
- 相同 commission/slippage
- study final session Close 賣出
- 不持續重複計算每個 MA 的 B&H

### Common evaluation start

使用 requested nearby periods 中最大 SMA 所需 warm-up：

```text
EvaluationStart
= max(
  user start date,
  first date where every requested SMA has valid MA(t-1)
)
```

Baseline、Box、B&H 全部從相同 EvaluationStart 開始。

B&H 不得取得 warm-up 期間報酬。

---

## 14. Counterfactual filter design

`MA_LONG_BASELINE` 必須作為完整獨立引擎同步運行，不可從 Box 結果事後估價。

當：

- baseline 建立真實 position
- Box track 當時 flat
- 同一 entry 因 BOX_ACTIVE 被阻止

則建立：

```text
FILTERED_BY_BOX
COUNTERFACTUAL_ENTRY
```

Counterfactual trade 完全沿用 baseline 的：

- raw/actual entry
- quantity
- exit
- commission
- slippage
- MFE/MAE
- holding days
- net PnL

退出時：

```text
COUNTERFACTUAL_EXIT
```

### Filter attribution

- Avoided losing trades：counterfactual net PnL < 0
- Missed winning trades：counterfactual net PnL > 0
- Breakeven：獨立列出
- Avoided gross loss：負 gross trading PnL 的絕對總和
- Missed gross gain：正 gross trading PnL 總和
- Net counterfactual effect：

```text
- sum(counterfactual net PnL)
```

正值表示 filter 整體避開的損失大於錯過的獲利。

Counterfactual capital 不得混入真實 Box equity。

---

## 15. Metrics schema

三個 tracks 統一輸出：

- Initial Capital
- Ending Equity
- Total Return
- CAGR
- Max Drawdown
- MDD start
- MDD bottom
- Recovery date
- Longest drawdown：trading days + calendar days
- Calmar
- Exposure
- Trade Count
- Win Rate
- Loss Rate
- Breakeven Rate
- Profit Factor
- Average Trade Return
- Median Trade Return
- Average Holding Days
- Median Holding Days
- Best Trade
- Worst Trade
- Total Commission
- Total Slippage Cost
- Equity curve
- Drawdown curve

若尚未 recovery：

```text
Recovery date = UNRECOVERED
```

Profit Factor 在沒有 gross loss時：

```text
NOT APPLICABLE
```

不以 Infinity 偽裝普通數值。

---

## 16. Local MA robustness

對 selected MA 與所有 requested nearby periods 分別執行，絕不共享 box state。

輸出 period curves：

- Total Return
- CAGR
- MDD
- Calmar
- Exposure
- Trade Count

Selected MA 單獨突出。

### Neighborhood summaries

對半徑：

```text
±1
±2
±3
±5
```

分別計算可用 periods 的：

- median
- min
- max

指標：

- Total Return
- CAGR
- MDD
- Calmar

若使用者設定的 Nearby Range 小於某個 summary 半徑：

```text
UNAVAILABLE — PERIODS NOT RUN
```

不得偷偷補跑。

只顯示 plateau/spike evidence，不自動替使用者選 MA。

---

## 17. Audit and chart event schema

每筆 event 至少保存：

```text
event_id
event_date
event_phase: OPEN / INTRADAY / CLOSE
strategy_revision
ticker
provider
data_fingerprint
config_hash
sma_period
visual_ma_t
execution_ma_t_minus_1
OHLC
setup_state_before/after
position_state_before/after
box_id
breakout_attempt_id
position_id
BoxHigh_before/after
BoxLow_before/after
tolerance_mode/value
supporting contacts
stop_raw
planned entry
raw fill
actual fill
risk entry
risk stop
risk distance
quantity
commission
slippage
reason_code
source-information cutoff
```

Reason codes至少包含使用者列出的所有 codes，並新增：

- `BOX_FORMING_NOT_READY_ATR`
- `NO_ENTRY_OPEN_AT_OR_BELOW_STOP`
- `RETEST_WAIT_EXPIRED`
- `BOX_CONSUMED_BY_ENTRY`
- `NO_ENTRY_ALREADY_LONG`

### Chart overlay

每個 period 可載入：

- Candles
- SMA
- Box shading
- BoxHigh/BoxLow
- Entanglement
- Boundary updates
- Breakouts/down breaks
- Failed attempts
- Retest touch/rebound
- Entries/exits
- Active stop line
- Holding interval
- Reason markers

Stop line只在 position active 時存在，不向持倉結束後延伸。

交易點擊後預設定位：

```text
Entry 前 20 bars
至
Exit 後 10 bars
```

並可切回 full-period overview。

Chart export：

- Full-period PNG
- Full-period SVG
- 當前 zoom PNG
- Audit JSON

Export 必須包含所有可見交易與箱型 annotations。

---

## 18. Persistence and API architecture

使用 additive schema，不修改舊結果：

### New tables

```text
ma_box_studies
ma_box_runs
ma_box_events
ma_box_counterfactual_trades
```

`ma_box_runs.track`：

```text
MA_LONG_BASELINE
MA_BOX_LONG_V1
BUY_AND_HOLD
```

B&H 每個 study 儲存一次。

### Study identity

Config hash必須涵蓋：

- ticker
- date range
- selected MA
- nearby range
- step
- all periods
- revision
- execution policy
- capital
- sizing
- costs
- force-close
- boundary mode/value
- breakout/retest timeout
- data fingerprint

### Dedicated endpoints

```text
POST /api/ma-box/studies
GET  /api/ma-box/studies/{study_id}
GET  /api/ma-box/studies/{study_id}/summary
GET  /api/ma-box/studies/{study_id}/runs/{period}/{track}
GET  /api/ma-box/studies/{study_id}/chart/{period}
GET  /api/ma-box/studies/{study_id}/counterfactuals/{period}
GET  /api/ma-box/studies/{study_id}/export/{period}
```

使用獨立背景工作類型：

```text
MA_BOX_LONG_STUDY
```

Nearby SMA 切換只載入已完成 run，不重新送出 backtest。

前端建立獨立頁面，例如：

```text
/ma-box
```

舊 production strategy selector 保持不變。

---

## 19. Frozen test matrix

Luna implementation 必須至少完成：

1. 四天三根貫穿且 close side 切換 → Box starts  
2. 三根貫穿但 closes 同側 → no box  
3. Equality close 不提供 side switch  
4. Box 不可 retroactive  
5. 持倉中形成 Box → 不 exit  
6. BOX_ACTIVE 阻止 normal entry  
7. Filtered entry 與 baseline canonical execution 相等  
8. Breakout close 不得同日 entry  
9. Indicative risk ≤5% → DIRECT_ENTRY_ELIGIBLE  
10. Indicative risk >5% → WAIT_RETEST  
11. Next-open actual risk ≤5% → direct entry  
12. Next-open gap risk >5% → no entry  
13. Next-open price ≤stop → no entry  
14. Retest Low≤MA 且 Close>MA → close 後確認  
15. Retest 不得成交在當日 Low、MA 或 Close  
16. Retest next-open risk≤5% → entry  
17. Retest 與 Close≤BoxHigh 同日 → retest 優先  
18. Non-retest Close≤BoxHigh → failed/reactivated  
19. Rebreakout → new attempt ID  
20. WAIT_RETEST 20-session expiry  
21. Down break while flat → no short  
22. Down break while long → no secondary exit  
23. MA−1.5% intraday fill → stop level  
24. MA stop gap-through → Open  
25. Direct/retest open entry後同日 stop可觸發  
26. No fixed profit target  
27. Counterfactual lifecycle exactly equals baseline  
28. Counterfactual capital不影響實際 equity  
29. Nearby periods box states完全隔離  
30. Current breakout bar不可先更新 boundary  
31. ATR tolerance frozen for box lifecycle  
32. Contact clustering每個 OHLC weight=1  
33. Boundary tie-break deterministic  
34. Boundary不得交叉  
35. Extreme wick不能在沒有更高 contact evidence時重畫  
36. Invalidated box必須等待四根新 bars rearm  
37. OHLC Heuristic green path O-L-H-C  
38. OHLC Heuristic red path O-H-L-C  
39. Entry/exit commission reconciliation  
40. Slippage reconciliation  
41. Forced end-date exit  
42. Common evaluation start fairness  
43. B&H 不取得 warm-up return  
44. Full no-lookahead mutation test  
45. Event/chart values與 canonical audit一致  
46. Existing Simple/Advanced regression全部通過  
47. Existing cache/history rows byte-for-byte不變  

---

## 20. Migration risks and resolutions

### Legacy selector contamination

風險：新增 enum 後出現在舊 production selector。

解法：使用 dedicated request model、endpoint、page；不修改 legacy selector。

### Existing history relabeling

風險：舊 Simple/Advanced 結果被新名稱解讀。

解法：新 tables、新 revision；不 migration 舊 strategy values。

### Same-day ordering

風險：completed-close breakout 被回填在當日價格。

解法：所有 Box close signals 最早 next open。

### Visual MA vs execution MA

風險：MA(t) 與 MA(t-1) 混用。

解法：event schema 同時保存兩者並標示用途。

### Box and position state collision

風險：Box 形成時誤平 long。

解法：setup state 與 position state正交。

### Boundary chasing

風險：突破 bar先拉高 BoxHigh。

解法：breakout/down-break永遠先於當日 boundary update。

### Counterfactual double counting

風險：shadow trade混入真實 capital。

解法：獨立 baseline ledger，只作 attribution。

### Result size

風險：多 period K線與 audits 造成超大單一 JSON。

解法：study/run/event分開儲存，圖表 lazy-load。

### Warm-up bias

風險：短 MA、長 MA和 B&H evaluation start 不一致。

解法：所有 tracks 使用 requested max MA 的共同起點。

### Reproducibility

風險：資料 cache 更新後同 study ID 代表不同 bars。

解法：data fingerprint與 config hash為 identity 必要欄位。

---

## Remaining ambiguities

會影響交易結果的 ambiguity：`NONE`

本規格已凍結以下原本未明確部分：

- Boundary tolerance：`0.10 × completed ATR14`，box creation時固定
- Initial box：使用完整四根 lookback bars
- Breakout bar：先判 breakout，不參與當日 boundary update
- Contact update：新 contact count 必須嚴格更高
- WAIT_RETEST lifetime：20個後續 trading sessions
- Retest vs failed breakout：合法 retest優先
- Failed breakout：原 box reactivated，下一次使用新 attempt ID
- Invalidation rearm：必須四根全新的 completed bars
- Direct/retest entry：next-open actual price
- Risk calculation：含 buy slippage、不含 commission
- V1 MA type：SMA only
- V1 exit：canonical MA stop或forced end；沒有TP
- Execution policy：OHLC Heuristic，不是 adverse-first

# MA_BOX_LONG_V1 SPEC FROZEN

## LUNA MAX IMPLEMENTATION HANDOFF

Luna 只能依本規格實作，並遵守：

1. 先把本規格序列化成 immutable spec artifact 並產生 SHA-256。
2. 不得改動 Simple、Advanced、Advanced + Day1Stop。
3. Normal entry、MA stop、Portfolio、cost、OHLC policy必須重用 canonical implementation。
4. 新策略使用獨立 backend namespace、API、資料表與前端頁面。
5. 不加入舊 production strategy selector。
6. 不實作 MA optimizer、ranking、score或best-period推薦。
7. 不加入 ATR breakout、volume filter、profit target或額外 stop。
8. 所有 tests通過前不得產生正式 historical study。
9. 必須驗證舊 runtime、executions、PnL、equity、audits皆無差異。
10. 若實作需要偏離本規格，立即停止並回報，不得自行解釋。

本 Sol 階段只完成 specification。尚未修改程式、尚未執行測試、尚未啟動 Luna implementation。

MA_BOX_LONG_V1 MASTER SPEC REVIEW COMPLETE
