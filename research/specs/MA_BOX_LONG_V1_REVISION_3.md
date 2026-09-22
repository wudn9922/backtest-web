# MA_BOX_LONG_V1 — Frozen Specification Revision 3

## SECTION A — MA_BOX_LONG_V1 MASTER SPEC

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

## SECTION B — MA_BOX_LONG_V1 SPEC AMENDMENT — FROZEN REVISION 2

## 1. 修正後條文

### A. Direct Breakout Two-Stage Gate

Breakout day `t` 於收盤後確認：

```text
Close(t) > BoxHigh
```

其中 `BoxHigh` 是該 session 開始前已知、且尚未被 breakout bar 更新的 boundary。

#### Stage A — Structural Gate

```text
Stop_next = SMA(t) × 0.985

BoxRiskDistance
= (BoxHigh - Stop_next) / BoxHigh
```

只有：

```text
0 < BoxRiskDistance <= 0.05
```

才能進入：

```text
DIRECT_ENTRY_ELIGIBLE
```

若：

```text
BoxRiskDistance > 0.05
```

則：

```text
NO_ENTRY_BOX_RISK_GT_5
WAIT_RETEST
```

若：

```text
BoxRiskDistance <= 0
```

則：

```text
NO_ENTRY_BOX_RISK_NOT_POSITIVE
WAIT_RETEST
```

原本以 breakout Close 計算 indicative risk 的 eligibility gate，正式刪除。

#### Stage B — Next-Open Execution Safety

若 Stage A 通過，t+1：

```text
ActualEntry
= Open(t+1) × (1 + buy_slippage)

ActualRisk
= (ActualEntry - Stop_next) / ActualEntry
```

只有：

```text
ActualEntry > Stop_next
AND
ActualRisk <= 0.05
```

才建立 direct entry。

若 gap 造成：

```text
ActualRisk > 0.05
```

則：

```text
NO_ENTRY_GAP_RISK_GT_5
WAIT_RETEST
```

若：

```text
ActualEntry <= Stop_next
```

則：

```text
NO_ENTRY_OPEN_AT_OR_BELOW_STOP
WAIT_RETEST
```

Risk distance 包含 buy slippage 後成交價，但不包含 commission。

---

### B. Initial Box Formation Bars

最近四根 completed bars 中，只使用符合：

```text
Low(i) <= SMA(i) <= High(i)
```

且實際參與 entanglement 判定的 qualifying bars。

- 三根 qualifying：使用三根
- 四根 qualifying：使用四根
- Qualifying bar 即使 Close 恰等於 MA，仍可參與初始 High/Low；但 neutral Close 不提供 side-switch 證據

初始邊界：

```text
BoxHigh_initial
= max(High of qualifying formation bars)

BoxLow_initial
= min(Low of qualifying formation bars)
```

非 qualifying 第四根不得進入：

- initial boundary
- initial contact pool
- initial midpoint calculation

初始 midpoint：

```text
InitialMidpoint
= (BoxHigh_initial + BoxLow_initial) / 2
```

---

### C. Boundary Contact Semantics

Upper boundary eligible fields：

```text
High
Open
Close
```

Lower boundary eligible fields：

```text
Low
Open
Close
```

明確禁止：

```text
Low  -> Upper contact
High -> Lower contact
```

Open、Close 的 field type 可供兩側使用，但實際分區仍依價格相對 frozen initial midpoint：

```text
Upper pool: eligible price >= InitialMidpoint
Lower pool: eligible price <= InitialMidpoint
```

若 Open/Close 恰等於 midpoint，可同時存在於兩個候選池。

所有 eligible contacts：

```text
weight = 1
```

不得給 High、Low 額外權重。

其他 clustering、strictly-better contact evidence、distinct-bar、MAD 與 deterministic tie-break 規則維持 Revision 1。

---

### D. Boundary Tolerance

V1 固定：

```text
boundary_contact_tolerance_mode
= ATR_NORMALIZED

boundary_contact_atr_period
= 14

boundary_contact_tolerance_multiplier
= 0.10
```

Box 建立時：

```text
boundary_contact_tolerance
= 0.10 × ATR14(box creation completed day)
```

實際數值在該 box lifecycle 內保持不變。

必須寫入：

- Study config
- Config hash
- Box audit
- Boundary-update audit
- Chart tooltip
- Export data

Clustering function 必須透過明確 config 接收 tolerance，不得在函式深處 hard-code `0.10`。

這是 V1 frozen historical semantics；未來改動必須升版。

---

### E. WAIT_RETEST Lifecycle

刪除：

```text
breakout_attempt_max_sessions = 20
RETEST_WAIT_EXPIRED
```

WAIT_RETEST 沒有時間型 timeout。

它持續到第一個結構性終止事件：

1. 成功 retest entry
2. Failed breakout
3. Close < BoxLow
4. 新的 causal independent box lifecycle
5. Study end

#### Deterministic priority

每個 WAIT_RETEST completed close 依序處理：

1. `Close < BoxLow`
   - `BEAR_BOX_BREAK`
   - `BOX_INVALIDATED`

2. Valid retest：

```text
Low(t) <= SMA(t)
AND
Close(t) > SMA(t)
```

   - `RETEST_CONFIRMED`
   - 最早 t+1 execution

3. 非 valid retest 且：

```text
Close(t) <= BoxHigh
```

   - `FAILED_BOX_BREAKOUT`
   - 結束目前 attempt
   - `BOX_REACTIVATED`
   - 回到 `BOX_ACTIVE`

4. 新 independent entanglement lifecycle：
   - 最近四根的 qualifying formation bars 全部晚於原 breakout date
   - 再次滿足 frozen entanglement condition
   - 且前述 1–3 均未發生

   則：

```text
BOX_INVALIDATED
reason = SUPERSEDED_BY_NEW_BOX
```

並建立：

- 新 box ID
- 新 qualifying formation set
- 新 boundaries
- 新 tolerance snapshot
- `BOX_ACTIVE`

5. 否則維持 `WAIT_RETEST`

Study end：

- flat：attempt 以 `STUDY_END_UNFILLED` 結束
- long：依既有 `FORCED_END_OF_TEST_EXIT`

因此 WAIT_RETEST 可超過20 sessions，但不得跨 failed breakout、bear break、box invalidation 或新 box lifecycle 延續。

---

## 2. 受影響的 State Transitions

| 原狀態 | 條件 | 修正後狀態 |
|---|---|---|
| BOX_ACTIVE | Close > BoxHigh，BoxRisk 0–5% | BREAKOUT_CONFIRMED → DIRECT_ENTRY_ELIGIBLE |
| BOX_ACTIVE | Close > BoxHigh，BoxRisk >5% | BREAKOUT_CONFIRMED → WAIT_RETEST |
| BOX_ACTIVE | BoxRisk ≤0 | BREAKOUT_CONFIRMED → WAIT_RETEST |
| DIRECT_ENTRY_ELIGIBLE | Next-open actual risk ≤5% 且 entry>stop | LONG_POSITION |
| DIRECT_ENTRY_ELIGIBLE | Gap actual risk >5% | WAIT_RETEST |
| DIRECT_ENTRY_ELIGIBLE | Actual entry≤stop | WAIT_RETEST |
| WAIT_RETEST | Valid completed-close retest | RETEST_CONFIRMED |
| RETEST_CONFIRMED | Next-open risk通過 | LONG_POSITION |
| RETEST_CONFIRMED | Next-open risk未通過 | WAIT_RETEST |
| WAIT_RETEST | 非retest且 Close≤BoxHigh | FAILED_BREAKOUT → BOX_REACTIVATED |
| WAIT_RETEST | Close<BoxLow | BEAR_BOX_BREAK → BOX_INVALIDATED |
| WAIT_RETEST | 新 independent entanglement | 舊 BOX_INVALIDATED → 新 BOX_ACTIVE |
| WAIT_RETEST | 經過任意固定天數 | 無轉移；仍為 WAIT_RETEST |

刪除所有：

```text
Breakout Close indicative-risk eligibility
20-session expiry
RETEST_WAIT_EXPIRED
```

Entanglement建立狀態不變，但初始 boundaries/contact pool 改為只使用 qualifying formation bars。

---

## 3. 受影響的 Tests

### Formation and contacts

1. 三根 qualifying 加一根 nonqualifying：

```text
Initial BoxHigh/BoxLow
只來自三根 qualifying bars
```

2. 四根 qualifying：

```text
四根全部使用
```

3. Nonqualifying bar 不得進入 initial contact pool 或 midpoint。

4. Upper clustering：

```text
High/Open/Close 可計數
Low 永遠不得提供 upper contact
```

5. Lower clustering：

```text
Low/Open/Close 可計數
High 永遠不得提供 lower contact
```

6. 相同 Open/Close field type 可依 midpoint 分區成 upper 或 lower candidate。

7. `0.10 × ATR14` fixture：
   - tolerance 內的視覺同水平 contacts 必須成為同一 cluster
   - tolerance 外的明顯不同水平不得合併

8. Audit/config/chart 顯示完全相同的 frozen tolerance value。

### Structural and execution risk

9. BoxHigh-to-stop risk >5%：

```text
NO_ENTRY_BOX_RISK_GT_5
WAIT_RETEST
```

10. BoxHigh-to-stop risk ≤5%，next-open gap 後 actual risk >5%：

```text
NO_ENTRY_GAP_RISK_GT_5
WAIT_RETEST
```

11. BoxHigh-to-stop risk ≤5%，且 actual-open risk ≤5%：

```text
Direct entry
```

12. BoxRisk≤0：

```text
NO_ENTRY_BOX_RISK_NOT_POSITIVE
WAIT_RETEST
```

13. Breakout Close 不得取代 BoxHigh 作 Stage A structural gate。

使用者原測試敘述：

> BoxHigh risk >5%，但 breakout Close risk <5%

在正價格、`Close > BoxHigh`、相同 stop 下數學上不可能成立，因為：

```text
Risk(P) = 1 - Stop/P
```

會隨 `P` 增加而增加。

因此此 fixture 改為兩項有效測試：

- Stage A 明確只讀 BoxHigh，不讀 Close
- 驗證 monotonic invariant：

```text
Close > BoxHigh
=> Risk(Close) > Risk(BoxHigh)
```

這不改變使用者規則，只移除無法成立的測試資料。

### WAIT_RETEST

14. WAIT_RETEST 超過20 sessions且沒有結構失效：

```text
仍為 WAIT_RETEST
```

15. WAIT_RETEST 遇 valid retest：

```text
RETEST_CONFIRMED
```

即使 `Close<=BoxHigh`，仍依 frozen precedence 優先處理 retest。

16. WAIT_RETEST 遇非retest且 `Close<=BoxHigh`：

```text
FAILED_BOX_BREAKOUT
BOX_REACTIVATED
```

17. Failed breakout 後下一次突破取得新 attempt ID。

18. WAIT_RETEST 遇 `Close<BoxLow`：

```text
BEAR_BOX_BREAK
BOX_INVALIDATED
```

19. WAIT_RETEST 出現全部為 breakout 後形成的全新 entanglement：

```text
舊 box invalidated
新 box ID建立
```

20. 沒有任何時間型 expiry reason code。

21. Study end前一直有效但未成交的 WAIT_RETEST：

```text
STUDY_END_UNFILLED
```

---

## 4. 是否仍有 Ambiguity

影響策略結果的 ambiguity：`NONE`

已明確凍結：

- Stage A 使用 BoxHigh，不使用 breakout Close
- Stage B 使用 next-open slippage後實際價格
- Initial box只使用 qualifying formation bars
- Upper/Lower OHLC contact eligibility
- ATR tolerance配置與生命週期
- WAIT_RETEST沒有固定時間 timeout
- Retest、failed breakout、bear break與新 box的處理優先順序
- 新 causal structure如何建立獨立 lifecycle
- Study end如何關閉未成交 attempt

`0.10 × ATR14` 的「PROVISIONAL」只表示未來可在新版本研究，不代表 V1執行時可變；對 `MA_BOX_LONG_V1` 歷史語意而言它是固定值。

MA_BOX_LONG_V1 SPEC AMENDMENT ACCEPTED  
MA_BOX_LONG_V1 SPEC FROZEN REVISION 2

## LUNA MAX IMPLEMENTATION HANDOFF

Implementation authority：

```text
MA_BOX_LONG_V1 MASTER SPEC
+
MA_BOX_LONG_V1 SPEC AMENDMENT REVISION 2
```

若兩者衝突，以 Revision 2 amendment 為準。

Luna 必須：

1. 先將完整 Revision 2 specification保存成 immutable spec artifact並產生 SHA-256。
2. 實作前驗證 authoritative entry、stop、OHLC Heuristic及cost helpers未改變。
3. 刪除所有 Close-based indicative direct-entry gate。
4. Stage A只使用 breakout snapshot BoxHigh與`SMA(t)×0.985`。
5. Stage B使用next-open slippage後實際買價。
6. Initial boundaries及initial contacts只使用qualifying formation bars。
7. Upper contacts只接受High/Open/Close；lower只接受Low/Open/Close。
8. 將ATR14 multiplier 0.10作為顯式、可序列化config。
9. 不加入任何session timeout。
10. 依本 amendment的WAIT_RETEST priority實作結構性失效。
11. 完成所有Revision 1 tests及上述amended tests。
12. 不修改legacy strategies、舊cache、舊history或production selector。
13. 若任何實作需要改變Revision 2語意，立即停止，不得自行決定。

本輪未修改任何程式，也未開始implementation。

## SECTION C — REVISION 3 AMENDMENT

【模型】

模式：
Luna Max — CORRECTNESS FIX PASS ONLY

Gemini：
不用

Grok：
不用

==================================================
AUTHORITY
==================================================

目前 MA_BOX_LONG_V1
尚未通過 Sol Final Review。

正式 verdict：

FAIL

不得：

開始真股票研究
開始 GitHub Pages deployment
開始 Render deployment
開始 PWA/cloud migration
宣稱 production ready。

本輪只能修正
Sol Final Review 已確認的 defects。

Authoritative specification 順序：

1.
MA_BOX_LONG_V1 MASTER SPEC

2.
MA_BOX_LONG_V1 SPEC AMENDMENT
FROZEN REVISION 2

3.
本 prompt 中的
REVISION 3 AMENDMENT

若衝突：

Revision 3
>
Revision 2
>
Master Spec。

==================================================
REVISION 3 AMENDMENT
==================================================

Revision 2 中：

WAIT_RETEST
→ SUPERSEDED_BY_NEW_BOX

這條 transition
正式刪除。

原因：

Frozen retest：

Low(t) <= SMA(t)
AND
Close(t) > SMA(t)

而 entanglement 所需要的
qualifying Above bar：

Low(t) <= SMA(t) <= High(t)
AND
Close(t) > SMA(t)

必然先符合 valid retest。

因此：

WAIT_RETEST priority 4
new independent entanglement

在 literal frozen semantics 下不可達。

不得：

修改 retest 定義

不得：

降低 retest priority

不得：

為了讓舊 transition 可達
增加額外條件。

正確修正：

刪除該 transition。

==================================================
REVISION 3 — FROZEN WAIT_RETEST PRIORITY
==================================================

每個 completed session：

1.

若：

Close(t) < BoxLow

則：

BEAR_BOX_BREAK
BOX_INVALIDATED

結束 current attempt。

--------------------------------------------------

2.

否則若：

Low(t) <= SMA(t)
AND
Close(t) > SMA(t)

則：

MA_RETEST_TOUCH
MA_RETEST_REBOUND
RETEST_CONFIRMED

最早：

t+1

才可 execution。

--------------------------------------------------

3.

否則若：

Close(t) <= BoxHigh

則：

FAILED_BOX_BREAKOUT

關閉 current attempt

same historical box：

BOX_REACTIVATED
BOX_ACTIVE。

下一次 breakout：

new attempt ID。

--------------------------------------------------

4.

否則：

保持：

WAIT_RETEST。

==================================================
NO WAIT_RETEST NEW-BOX SUPERSESSION
==================================================

刪除 production path：

SUPERSEDED_BY_NEW_BOX

若此 reason code
只屬於該 path：

從 MA_BOX_LONG_V1
active reason-code set 移除。

不得以固定時間
讓 WAIT_RETEST 失效。

WAIT_RETEST
仍然可以持續任意 session。

==================================================
NEW BOX AFTER INVALIDATION
==================================================

新的 independent box
只能在舊 box：

真正 BOX_INVALIDATED

之後重新形成。

仍遵守：

必須使用 invalidation 後
4 根全新的 completed bars。

不得重用：

舊 box lifecycle
中的 formation bars。

這項既有 rearm semantics
保留。

==================================================
IMPORTANT
==================================================

如果 long position 存在，
仍允許未來依 canonical rules
偵測新的 entanglement。

Position state
與 setup state
仍然正交。

Revision 3
只刪除：

WAIT_RETEST 中
不可達的 new-box supersession。

==================================================
FIX 1 — DAILY EQUITY LEDGER
==================================================

這是目前最高優先級
blocking correctness defect。

Current defect：

_result_from_track()

在整個 simulation 完成後，

使用 final Portfolio state
重新對歷史 Close
呼叫：

portfolio.equity(historical_close)

造成：

整條 equity curve
使用最終 cash/position state。

Force-close 後通常：

quantity = 0

所以整段歷史
變成同一個 ending equity。

這是錯誤的。

==================================================
REQUIRED EQUITY ARCHITECTURE
==================================================

每一個 track：

MA_LONG_BASELINE

MA_BOX_LONG_V1

BUY_AND_HOLD

都必須建立：

IMMUTABLE DAILY LEDGER。

不能在 simulation 結束後
使用 final portfolio
重建過去。

==================================================
DAILY LEDGER ROW
==================================================

每個 evaluation session t
至少保存：

date

cash_end_of_day

quantity_end_of_day

close_price

market_value_close

equity_close

position_state

以及若架構適合：

daily realized PnL
cumulative realized PnL。

定義：

market_value_close
=
quantity_end_of_day
*
Close(t)

equity_close
=
cash_end_of_day
+
market_value_close。

==================================================
DAILY ORDER
==================================================

每個 session：

1.
使用 session-start state

2.
處理 Open execution

3.
依 OHLC_HEURISTIC
處理 intraday entry/stop

4.
處理所有 canonical executions

5.
處理 completed-close
setup signals

6.
若 final study session
且 position 尚存在：

先執行 canonical
FORCED_END_OF_TEST_EXIT
at final Close

7.
最後 snapshot：

immutable EOD ledger。

不得：

下一天再回頭修改
前一天 ledger。

==================================================
ENTRY + SAME-DAY STOP
==================================================

如果：

direct/retest/normal entry

在 Open 或 intraday 成交，

同一 session
依 OHLC Heuristic
又觸發 canonical stop，

則：

EOD ledger
必須反映：

position flat

以及真實剩餘 cash。

==================================================
BUY & HOLD LEDGER
==================================================

EvaluationStart：

Open 買入。

當天 EOD：

使用 Close mark。

之後每日：

quantity 固定
直到 final exit。

Final session：

先在 Close
執行 sell

再保存：

final cash
quantity=0
final equity。

==================================================
METRIC INPUT
==================================================

所有 path-dependent metrics：

Equity curve

Drawdown curve

Max Drawdown

MDD start

MDD bottom

Recovery date

Longest Drawdown

Calmar

Sharpe
若現有結果包含

Sortino
若現有結果包含

必須使用：

immutable daily equity ledger。

禁止：

使用 final portfolio
回填歷史。

==================================================
INITIAL CAPITAL ANCHOR
==================================================

Drawdown 計算
必須把：

Initial Capital

視為 equity peak 的初始基準。

不要因第一個 evaluation-day
已扣 commission

而遺失：

initial-capital → first EOD

可能產生的 drawdown。

優先使用現有 canonical metrics helper
接受 initial capital 的既有方式。

不得修改 canonical metrics semantics。

==================================================
TOTAL RETURN
==================================================

仍以：

Ending Equity / Initial Capital - 1

計算。

Ending Equity
必須與 final ledger row
完全一致。

==================================================
EQUITY REGRESSION TESTS
==================================================

新增 direct tests：

A.
B&H 手算 fixture：

價格有漲有跌，

daily equity
必須至少有多個不同 values。

B.
手算 B&H equity
逐日完全比對。

C.
人工可計算的非零 drawdown：

驗證：

MDD
start
bottom
recovery。

D.
MA baseline
至少一筆持倉：

equity 在持倉期間
必須隨 Close 變化。

E.
entry + same-day stop：

EOD cash/equity
手算一致。

F.
forced-end exit：

final ledger
與 Ending Equity
完全一致。

G.
重新執行相同 fixture：

daily ledger
byte-for-byte deterministic。

==================================================
FIX 2 — AUTHORITATIVE SPEC ARTIFACT
==================================================

Current artifact：

research/specs/
MA_BOX_LONG_V1_REVISION_2.md

只是 condensed rewrite。

它不能繼續作為
authoritative complete specification。

不要覆寫舊檔
假裝它以前就是完整版本。

保留舊檔作：

historical implementation artifact。

==================================================
NEW AUTHORITATIVE ARTIFACT
==================================================

建立：

research/specs/
MA_BOX_LONG_V1_REVISION_3.md

內容必須 VERBATIM 包含：

SECTION A
完整：
MA_BOX_LONG_V1 MASTER SPEC

SECTION B
完整：
MA_BOX_LONG_V1 SPEC AMENDMENT
FROZEN REVISION 2

SECTION C
完整：
本 prompt 的
REVISION 3 AMENDMENT。

不得：

摘要
改寫
刪節
重新描述
省略 tests
省略 API
省略 migration risk
省略 chart schema。

==================================================
SOURCE AVAILABILITY
==================================================

如果目前 Codex context
無法取得：

Master Spec
或
Revision 2 Amendment

的完整原文，

立即 STOP。

輸出：

AUTHORITATIVE SPEC SOURCE REQUIRED

不要根據舊 condensed artifact
自行重建內容。

==================================================
CANONICAL ARTIFACT BYTES
==================================================

新 artifact：

UTF-8
no BOM
LF line endings
exactly one trailing newline。

SHA-256：

直接 hash
MA_BOX_LONG_V1_REVISION_3.md
實際 bytes。

建立 sidecar：

MA_BOX_LONG_V1_REVISION_3.sha256

記錄：

strategy revision
spec revision = 3
actual SHA-256。

==================================================
PERSISTENCE IDENTITY
==================================================

之後所有新：

study
run
event

必須保存：

spec_revision = 3
spec_hash = Revision 3 actual hash。

目前：

ma_box_studies = 0

因此沒有 historical study
需要 migration/relabel。

不得：

把不存在的舊研究結果
偽裝成 Revision 3。

==================================================
FIX 3 — REMOVE UNREACHABLE PATH
==================================================

刪除：

WAIT_RETEST
→ SUPERSEDED_BY_NEW_BOX

production code。

刪除／更新：

對應 dead helper
dead branch
dead test
dead reason code

若確定只服務該 path。

不得：

保留永遠不可達 branch
只為了讓舊 spec 看起來有實作。

==================================================
REPLACEMENT TESTS
==================================================

新增：

1.
WAIT_RETEST 中
qualifying Above bar：

Low<=MA
Close>MA

必須走：

RETEST_CONFIRMED

不能 new box。

2.
WAIT_RETEST 中
non-retest Close<=BoxHigh：

FAILED_BREAKOUT
BOX_REACTIVATED。

3.
WAIT_RETEST
Close<BoxLow：

BOX_INVALIDATED。

4.
WAIT_RETEST
價格長期維持在：

Close>BoxHigh

且沒有 valid retest：

即使 >20
>40
>60 sessions

仍 WAIT_RETEST。

5.
只有舊 box
BOX_INVALIDATED 後，

使用4根全新 bars

才可建立 new box。

==================================================
FIX 4 — TEST TRACEABILITY
==================================================

Current：

47 total MA_BOX tests

不足以證明：

Master frozen test matrix
+
Revision 2 amendments
+
Revision 3。

建立：

research/specs/
MA_BOX_LONG_V1_TEST_TRACEABILITY_REV3.json

或等價 machine-readable artifact。

==================================================
TRACEABILITY CONTENT
==================================================

逐項列出：

requirement_id

source_spec

requirement_text

test_file

test_name

coverage_status：

DIRECT
COMBINED_DIRECT
MISSING。

==================================================
MASTER TEST MATRIX
==================================================

Master Spec
原始47項：

每一項都必須有：

DIRECT

或：

COMBINED_DIRECT

test。

不得：

只因相關 code
被其他 test 經過
就算 covered。

==================================================
REVISION 2 TEST MATRIX
==================================================

Revision 2 amended tests
也全部列入。

特別必須 direct cover：

3 qualifying +1 nonqualifying

4 qualifying

nonqualifying excluded from contacts/midpoint

Upper rejects Low

Lower rejects High

ATR tolerance clustering

tolerance audit identity

BoxHigh Stage A

Stage A does not read Close

risk monotonic invariant

Stage B gap risk

BoxRisk <=0

no timeout >20 sessions

retest precedence

failed breakout

new attempt ID

bear break

study-end unfilled attempt。

==================================================
REVISION 3 TEST MATRIX
==================================================

至少：

equity ledger correctness

nonzero MDD

WAIT_RETEST no supersession

new box only after invalidation

full artifact hash

local-summary radii

stepwise chart boundary

period-state isolation

exact counterfactual object parity。

==================================================
IMPORTANT
==================================================

不要求：

每個 requirement
一定一個獨立 Python function。

一個 test
可以直接驗證
多個緊密相關 requirement。

但 traceability
必須明確。

任何：

MISSING

=> fix pass 不得宣稱 complete。

==================================================
FIX 5 — LOCAL ROBUSTNESS CONTRACT
==================================================

Current implementation：

只有整個 requested range
一組：

median
min
max。

這不符合 frozen spec。

對：

selected period p

分別建立：

radius 1
radius 2
radius 3
radius 5。

==================================================
FOR EACH RADIUS
==================================================

考慮：

[p-r, p+r]

中：

實際已 run 的 periods。

輸出：

available_periods

expected_periods

status。

對：

Total Return
CAGR
MDD
Calmar

分別：

median
min
max。

==================================================
MISSING PERIOD RULE
==================================================

如果使用者 requested Nearby Range
不足以完整覆蓋該 radius：

例如只跑 ±2，

則：

±3
±5

必須：

status =
UNAVAILABLE_PERIODS_NOT_RUN

UI 顯示：

UNAVAILABLE — PERIODS NOT RUN。

不得：

偷偷補跑
也不得：

拿不完整 radius
假裝完整 summary。

==================================================
FIX 6 — SQLITE FOREIGN KEY REVIEW
==================================================

Sol review 發現：

declared FK 存在

但 runtime：

PRAGMA foreign_keys = 0。

先檢查 connection architecture。

==================================================
SAFE RULE
==================================================

如果可以只對：

MA_BOX dedicated DB connection

啟用：

PRAGMA foreign_keys = ON

而完全不改 legacy runtime semantics，

則：

啟用並測試。

==================================================
IF SHARED CONNECTION
==================================================

如果唯一方法
會改變：

legacy repository connection behavior

則：

不要直接修改 shared connection。

輸出：

DEFERRED_FOREIGN_KEY_ENFORCEMENT
REQUIRES_SOL_ARCHITECTURE_DECISION

此項：

不是 strategy correctness blocker。

不得為修非 blocking issue
破壞 legacy invariance。

==================================================
IF ENABLED
==================================================

測試：

orphan run insert fails

orphan event insert fails

study delete cascade
符合 schema

legacy regression
仍完全 PASS。

==================================================
FIX 7 — STUDY FAILURE LIFECYCLE
==================================================

如果可以只修改
dedicated MA_BOX endpoint/persistence
而不改 strategy semantics：

修正。

POST create study：

先建立：

status = RUNNING

study row。

再開始：

data acquisition
engine execution。

==================================================
SUCCESS
==================================================

完成：

status = COMPLETED。

==================================================
FAILURE
==================================================

data/provider/engine/persistence
任何 failure：

更新：

status = FAILED

保存：

sanitized error_code
sanitized error_message。

不得：

保存完整 stack trace
給 frontend。

Server log
可保留 debug trace。

==================================================
RUN ENDPOINT
==================================================

若 study：

RUNNING

但 run 尚不存在：

不要回普通：

MA_BOX_RUN_NOT_FOUND。

返回：

HTTP 409

code：

MA_BOX_STUDY_NOT_COMPLETE

status：

RUNNING。

若 FAILED：

HTTP 409

code：

MA_BOX_STUDY_FAILED

並提供 sanitized error。

如果這需要大幅修改
既有 job architecture：

STOP
報：

SOL DECISION REQUIRED。

==================================================
FIX 8 — STEPWISE CHART BOUNDARY
==================================================

Backend audit
是 authoritative。

Frontend：

不得：

用稀疏 update points
線性連接 BoxHigh/BoxLow。

Boundary：

在某次 close 後更新，

新值：

t+1 才生效。

因此 chart
必須畫：

STEPWISE CAUSAL BOUNDARY。

==================================================
BACKEND CHART PAYLOAD
==================================================

優先輸出：

每個 trading day
實際 effective：

box_high_effective

box_low_effective

box_id

setup_state。

或等價
足以直接畫 staircase
的 authoritative segments。

Frontend：

不得自己重新計算 boundary。

==================================================
BOX SHADING
==================================================

Box shaded region：

每個 session
使用同日 effective：

BoxHigh
BoxLow。

Boundary update
不得造成：

舊區段被新 boundary
回頭重畫。

==================================================
BOUNDARY TEST
==================================================

建立：

BoxHigh：

100
→ completed t update to105
→ new value effective t+1

chart payload 必須：

<=t：
100

>=t+1：
105

不能：

100到105畫斜線

也不能：

t之前全部變105。

==================================================
FIX 9 — CHART ZOOM / PAN
==================================================

目前只有：

crosshair。

補：

horizontal pan
zoom

以及：

Reset / Full Range

如果現有 chart library
已提供 native：

scroll
scale
pinch

優先啟用現有功能。

不要：

自製複雜 gesture engine。

==================================================
IMPORTANT
==================================================

本輪主要驗證：

source/config/test level。

真正 iPhone gesture
仍會在：

CLOUD/MOBILE PHASE

做實機 acceptance。

但目前 frontend
至少不能明確 disable：

scroll/zoom。

==================================================
FIX 10 — FULL IMAGE EXPORT
==================================================

仍然保持：

DEFERRED。

本輪不要因：

PNG/SVG export

重寫 chart engine。

正式標記：

CLOUD_MOBILE_REQUIRED_ITEM。

之後 cloud/mobile phase
不得再次 defer：

Full-period PNG
Full-period SVG
Current zoom PNG

或經 Sol 核准的
等價完整 export。

==================================================
FIX 11 — ATR PERIOD VERIFICATION
==================================================

Sol review文字中
出現：

0.10 × ATR10

但 authoritative V1：

ATR14。

確認 production：

Wilder ATR14。

確認 config：

period = 14。

新增 direct regression：

若：

ATR10 != ATR14

則 box tolerance
必須精確等於：

0.10 × ATR14

不得誤用 ATR10。

==================================================
FIX 12 — COUNTERFACTUAL DIRECT PARITY TEST
==================================================

已有 review-only synthetic
證明 counterfactual parity，

但正式 suite 缺 direct test。

新增 persisted test：

對每個 FILTERED_BY_BOX trade：

counterfactual：

entry date
raw fill
actual fill
quantity
commission
slippage
exit date
exit price
gross pnl
net pnl
MFE
MAE
holding days

必須與對應：

MA_LONG_BASELINE position

逐欄一致。

Counterfactual：

不得改：

Box cash
Box qty
Box equity。

==================================================
FIX 13 — PERIOD STATE ISOLATION
==================================================

新增 mutation test。

例如：

SMA23
SMA24
SMA25。

故意讓：

SMA23
形成不同 Box state。

確認：

SMA24/SMA25：

box id
boundaries
attempts
position
events

完全不變。

Nearby periods：

不得共享 mutable state。

==================================================
FIX 14 — OTHER MISSING DIRECT TESTS
==================================================

依 Sol review
補 direct regressions：

Box formation while long
does not exit

equal-contact candidate
does not update boundary

breakout candle
cannot chase boundary

down break while long
does not force exit

box consumption
freezes old box

study-end unfilled attempt

Stage A Close independence
end-to-end

Stage B transition

retest precedence

>20 session WAIT_RETEST

nonzero MDD

B&H manual equity。

==================================================
LEGACY PROTECTION
==================================================

修正前：

重新記錄
9 authoritative helper hashes。

修正後：

再次比對。

除非 Sol 明確授權：

9/9 必須完全相同。

Legacy suite：

全部重新執行。

Simple
Advanced
Advanced + Day1Stop

不得改。

Database legacy counts：

不得被 migration
無故改動。

==================================================
DO NOT USE REAL STOCKS
==================================================

仍然禁止：

SMCI
LULU
AAPL
或其他真實股票

作 correctness proof。

全部使用：

deterministic synthetic fixtures。

==================================================
FULL TEST EXECUTION
==================================================

完成後執行：

1.
MA_BOX dedicated suite

2.
Legacy backend suite

3.
All backend suite

4.
Frontend suite

5.
compileall

6.
production frontend build

7.
spec traceability validator

8.
determinism test
至少3次。

==================================================
TEST REPORT
==================================================

必須精確報：

passed
failed
skipped
xfail
deselected
warnings。

不要只寫：

all tests passed。

==================================================
EQUITY ACCEPTANCE
==================================================

特別輸出至少一個
人工可閱讀 fixture：

日期
Close
Cash
Quantity
Market Value
Equity
Drawdown

讓 Sol 可以手算。

==================================================
SPEC ARTIFACT ACCEPTANCE
==================================================

輸出：

Revision 3 artifact：

path
bytes
lines
SHA-256。

並確認：

VERBATIM Master Spec present

VERBATIM Rev2 Amendment present

VERBATIM Rev3 Amendment present。

==================================================
FIX PASS OUTPUT
==================================================

完成後只輸出：

1.
Files changed

2.
Revision 3 amendment implementation

3.
Equity ledger fix

4.
Manual equity fixture

5.
Metrics reconciliation

6.
Spec artifact verification

7.
Spec SHA-256

8.
Traceability matrix summary

9.
WAIT_RETEST dead-path removal

10.
Local robustness output fix

11.
ATR14 verification

12.
Counterfactual parity test

13.
Period-isolation test

14.
Chart stepwise-boundary fix

15.
Zoom/pan status

16.
Study failure lifecycle status

17.
SQLite FK enforcement status

18.
MA_BOX test exact counts

19.
Legacy test exact counts

20.
Frontend test exact counts

21.
Build / compile result

22.
Canonical helper hashes

23.
Determinism result

24.
Remaining blocking defects

25.
Remaining non-blocking defects

26.
Spec deviations

==================================================
PASS CONDITION
==================================================

不得輸出：

MA_BOX_LONG_V1 FIX COMPLETE

除非：

Equity ledger correct

MDD fixture correct

Revision3 full spec artifact correct

WAIT_RETEST unreachable path removed

all frozen requirements mapped

all required tests covered

local ±1/±2/±3/±5 correct

stepwise chart payload correct

no-lookahead still PASS

counterfactual parity PASS

period isolation PASS

legacy regression PASS

canonical helpers invariant

determinism PASS

spec deviation = NONE。

==================================================
IF BLOCKED
==================================================

如果：

完整 Master/Rev2原文不可取得

shared DB change會影響 legacy

或任何修正需要
改 frozen strategy semantics：

立即停止。

輸出：

SOL DECISION REQUIRED

不要自行決定。

==================================================
FINAL
==================================================

這是 correctness fix pass。

不是：

feature expansion
cloud migration
strategy redesign。

穩定性優先。

最後若全部成立：

MA_BOX_LONG_V1 CORRECTNESS FIX PASS COMPLETE
READY FOR SOL RE-REVIEW
