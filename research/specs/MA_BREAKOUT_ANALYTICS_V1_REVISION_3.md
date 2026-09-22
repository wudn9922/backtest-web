<!-- BEGIN SOURCE A: AUTHORITATIVE SOL FROZEN REVISION 2 OUTPUT -->
結論：Repo 稽核已完成，A–F 六項結果性決策均可凍結。沒有修改任何程式、測試、資料庫或既有規格。

MA_BOX_LONG_V1 Rev3 實際規格檔 SHA-256 已核對為：

`1edad0648095eb8261a79e6f9bf712f23a6dbb4db9271a1f0273ad7c79dbab0d`

# MA_BREAKOUT_ANALYTICS_V1 — Master Specification Revision 2

## 1. Authoritative Two-Day Rule audit

現有 production Advanced v2 的正式規則是：

```text
Long success:
Close(D2) > Close(D1)

Long failure:
Close(D2) <= Close(D1)
```

相等屬於失敗。

證據位於 [advanced_ma_breakout.py](C:/Users/user/Documents/Codex/2026-09-02/web-app-prototype-ui-mockup-readme/backtest-web/backend/app/backtest/strategies/advanced_ma_breakout.py:312)；測試亦明確驗證 D2 相等失敗：[test_strategy_rules.py](C:/Users/user/Documents/Codex/2026-09-02/web-app-prototype-ui-mockup-readme/backtest-web/backend/tests/test_strategy_rules.py:93)。

Short analytics 採完全鏡像：

```text
Short success:
Close(D2) < Close(D1)

Short failure:
Close(D2) >= Close(D1)
```

Repo 另有一套 MA_STRUCTURE research-only 定義：

```text
Bull: Close(D2) > High(D1)
Bear: Close(D2) < Low(D1)
```

它位於 [structure.py](C:/Users/user/Documents/Codex/2026-09-02/web-app-prototype-ui-mockup-readme/backtest-web/backend/app/optimization/structure.py:652)，不是 production Two-Day Rule，也不適用於本模組。

凍結決定：

```text
MA_BREAKOUT_ANALYTICS_V1 Two-Day Rule
= strict Close-over-Close rule
```

不加入 Higher High 條件。

---

## 2. Authoritative breakout-related repo audit

Repo 現況：

- 尚無 `MA_BREAKOUT_ANALYTICS_V1` module。
- Production Simple/Advanced 的 `MA+1%～1.5%` 是 entry zone，不是視覺突破。
- 舊 MA_STRUCTURE research 把 `MA+1%` 當 structural breakout，不得重用。
- MA_BOX 的 `Close > BoxHigh` 是箱型突破，也不是本模組的 MA breakout。
- 現有 Wilder ATR14 實作可重用：[indicators.py](C:/Users/user/Documents/Codex/2026-09-02/web-app-prototype-ui-mockup-readme/backtest-web/backend/app/backtest/indicators.py:13)。
- 現有 OHLC Heuristic 可重用：[execution.py](C:/Users/user/Documents/Codex/2026-09-02/web-app-prototype-ui-mockup-readme/backtest-web/backend/app/backtest/execution.py:108)。
- MA_BOX entanglement 的 causal predicate 可重用：[engine.py](C:/Users/user/Documents/Codex/2026-09-02/web-app-prototype-ui-mockup-readme/backtest-web/backend/app/ma_box/engine.py:368)。

本模組必須位於獨立 namespace；不得 import production strategy state、寫入 MA_BOX tables，或改動 MA_BOX 行為。

---

## 3. Day1 visual breakout recommendation

### Frozen choice

採用 percentage completed-close definition：

```text
M(t) = completed SMA_p(t)

Long Day1:
Close(t) >= M(t) × 1.002

Short Day1:
Close(t) <= M(t) × 0.998
```

Day1 使用 completed `MA(t)`，不是 execution `MA(t-1)`。

不加入：

- High-only crossing
- candle body ratio
- wick filter
- volume filter
- ATR gate
- gap filter

### Cross latch

Long：

1. `Close <= MA` 令 long latch 為 `ARMED`。
2. 首次 `Close >= MA×1.002` 建立 Day1 event。
3. 建立後為 `DISARMED`。
4. 只有之後另一 completed day 再次 `Close <= MA` 才重新 armed。

Short 鏡像：

1. `Close >= MA` → armed。
2. 首次 `Close <= MA×0.998` → Day1。
3. 之後必須再有 `Close >= MA` 才 re-arm。

Grey-zone 回落但仍在 MA 同一側，不會重複建立 event。

Study 開始前必須有至少一根有效 completed bar初始化 latch；不得把研究第一天中途已存在的趨勢自動當新突破。

---

## 4. 0.2% vs ATR comparison

| 定義 | 優點 | 問題 | V1 |
|---|---|---|---|
| ±0.2% | 與既有人工視覺語意一致；簡單、價格尺度不變 | 對不同波動率不是完全等價 | 採用 |
| ATR 0.05–0.20 | 波動標準化 | k 沒有既有 authority；易受 volatility regime 與 gap 影響 | 僅記錄 |
| Hybrid | 可抑制高波動微小穿越 | 增加第二門檻並可能排除低波動的清楚突破 | 不採用 |

每筆 event 仍保存：

```text
breakout_distance_pct
breakout_distance_atr
```

ATR distance 只作描述，不參與 V1 event eligibility。

---

## 5. Reference-entry formalization

令：

```text
R = SMA_p(D1-1)
```

Frozen reference entry：

```text
Long E = R × 1.01
Short E = R × 0.99
```

這是：

```text
統計基準進場價
```

不是：

- Day1 threshold
- actual fill
- production entry
- gap/no-chase order
- portfolio transaction

不計 quantity、commission、slippage 或 executable fill eligibility。

### Observation origin

Day1 突破必須等收盤才成立。因此：

```text
Signal time = D1 completed close
Target/stop path first evaluable point = D2 Open
```

Day1 intraday High/Low 不得回頭用於 target/stop resolution。

Day2-conditioned結果仍屬 retrospective analytics，因 Day2 success 要到 D2 close 才知道。

---

## 6. Dynamic-stop target design

對每個 target 獨立建立 outcome。

Long session `u`：

```text
Stop(u) = SMA_p(u-1) × 0.985
```

Short mirror：

```text
Stop(u) = SMA_p(u-1) × 1.015
```

每個 session 重新取得 dynamic stop；target level固定。

結果狀態：

```text
SUCCESS_TARGET_FIRST
FAIL_STOP_FIRST
RIGHT_CENSORED
```

### Open gap

Long：

```text
Open <= Stop   => Stop first
Open >= Target => Target first
```

Short：

```text
Open >= Stop   => Stop first
Open <= Target => Target first
```

### 同日兩者皆觸碰

沿用 OHLC Heuristic：

```text
Green, Close >= Open:
O → L → H → C

Red, Close < Open:
O → H → L → C
```

因此：

- Long green：stop before target
- Long red：target before stop
- Short green：target before stop
- Short red：stop before target

---

## 7. ATR target design

ATR 採 canonical Wilder ATR14。

Frozen snapshot：

```text
ATR_snapshot = ATR14(D1)
```

D1 收盤後固定，整筆 event 不再更新。

Long：

```text
3%       = E × 1.03
0.5 ATR  = E + 0.5 × ATR_snapshot
1.0 ATR  = E + 1.0 × ATR_snapshot
1.5 ATR  = E + 1.5 × ATR_snapshot
2.0 ATR  = E + 2.0 × ATR_snapshot
3.0 ATR  = E + 3.0 × ATR_snapshot
```

Short：

```text
3%       = E × 0.97
0.5 ATR  = E - 0.5 × ATR_snapshot
...
3.0 ATR  = E - 3.0 × ATR_snapshot
```

ATR14 missing、nonfinite 或 `<=0`：

- ATR targets 標為 `TARGET_NOT_EVALUABLE_ATR`
- 不放入相應 denominator
- 不影響 percentage +3% target 的可評估性

---

## 8. Nested volume threshold design

```text
VolumeChange
= Volume(D1) / Volume(D1-1) - 1
```

條件：

```text
VOL_GE_10 = change >= 0.10
VOL_GE_20 = change >= 0.20
VOL_GE_30 = change >= 0.30
VOL_LT_10 = change < 0.10
```

門檻是 nested：

```text
+35% 同時屬於 GE10、GE20、GE30。
```

不可改成互斥 buckets。

若 previous volume missing、nonfinite 或 `<=0`，或 Day1 volume missing、nonfinite、negative：

```text
VOLUME_NOT_EVALUABLE
```

不進 volume denominator。

Day1 volume 為零但 previous volume有效時，仍是有效的 `-100%` observation。

---

## 9. Day2 + volume conditional design

必須分別保存：

```text
P(Day2 success | Breakout)
P(Vol>=x | Breakout)
P(Day2 success AND Vol>=x | Breakout)
```

Joint probability 的 eligible set 必須同時具備：

- evaluable D2
- evaluable volume

Conditional target sets：

```text
Day2 success
VOL_GE_10
VOL_GE_20
VOL_GE_30
Day2 AND VOL_GE_10
Day2 AND VOL_GE_20
Day2 AND VOL_GE_30
```

每個 target、condition、direction、period及entanglement cohort 都有獨立 numerator/denominator。

---

## 10. No-horizon target semantics

不得存在：

```text
target_max_days
5D target
10D target
20D target
timeout failure
```

Target observer從 D2 Open 開始，直到：

1. target first
2. dynamic stop first
3. study end → right censored

Condition 已經成立或失敗，不得改變 target observer 的既有歷史結果。

---

## 11. Day2 failure state machine

Eligibility：

```text
Long failure  = Close(D2) <= Close(D1)
Short failure = Close(D2) >= Close(D1)
```

Observation從 D2 completed close之後開始；D2本身不得被重新解讀成 terminal outcome。

第一個可判定 session 是 D3。

狀態：

```text
OBSERVING_FAILURE_PATH
→ RETEST_REBOUND / RETEST_REJECTION
→ RETURN_TO_BEAR / RETURN_TO_BULL
→ SIDEWAYS
→ TREND_CONTINUATION_AWAY
→ RIGHT_CENSORED
```

一旦 terminal outcome 成立，事件停止；後續狀態不得覆寫它。

---

## 12. MA retest ±0.1% semantics

對 follow-up day `u`：

```text
ZoneLow  = MA(u) × 0.999
ZoneHigh = MA(u) × 1.001
```

Range intersection：

```text
Low(u) <= ZoneHigh
AND
High(u) >= ZoneLow
```

Long：

```text
range intersects zone
AND Close(u) > MA(u)
=> MA_RETEST_REBOUND
```

Short：

```text
range intersects zone
AND Close(u) < MA(u)
=> MA_RETEST_REJECTION
```

使用 completed `MA(u)`，於當日 close 後判定。

`Close == MA` 不構成 rebound/rejection。

---

## 13. Return-to-bear/bull recommendation

不採原始 `Close < MA` 或 ±0.1%，避免把 zone 內微小收盤穿越誤判成正式 regime reversal。

Frozen：

```text
Long RETURN_TO_BEAR:
Close(u) <= MA(u) × 0.998

Short RETURN_TO_BULL:
Close(u) >= MA(u) × 1.002
```

理由：

- 與 Day1 visual breakout 使用同一 clear-state 語意
- 與 ±0.1% retest zone清楚分離
- 無新增 ATR threshold
- completed-close causal

---

## 14. Sideways recommendation

Frozen choice：

```text
Reuse MA_BOX_LONG_V1 Rev3 causal visual-box semantics.
```

不另建 range-compression threshold，也不將兩套規則 OR/AND 混合。

建立 read-only `VisualBoxObserver`，不得使用 MA_BOX 的 position、entry、risk gate 或 persistence。

Observer重用：

- exactly 最近4根 completed bars
- 至少3根 qualifying：
  `Low <= MA(t) <= High`
- qualifying closes中至少一個 above、一個 below
- non-neutral sequence至少一次 side switch
- neutral可作 formation bar但不提供 side evidence
- initial box只使用 qualifying formation bars
- Wilder ATR14有效
- tolerance = `0.10 × ATR14`，creation時固定
- frozen contact、boundary-update及 t+1 effective semantics
- invalidation後必須使用4根全新 completed bars rearm

`SIDEWAYS` 於 follow-up close 後，VisualBoxObserver 顯示有效 `BOX_ACTIVE`，且較高優先級 outcome 未成立時確認。

這不是 maximum follow-up horizon；四根只是 minimum causal confirmation structure。

---

## 15. Trend-continuation-away recommendation

採與 Day1一致的 percentage visual threshold，不新增 ATR gate。

Long：

```text
Close(u) >= MA(u) × 1.002
```

Short：

```text
Close(u) <= MA(u) × 0.998
```

條件只在：

- D2已失敗
- observation已進入D3或之後
- 先前未發生其他 terminal outcome
- 同日較高優先級 outcome也未成立

時評估。

ATR distance仍保存為 diagnostic，不是 gate。

---

## 16. Terminal precedence

每個 follow-up completed day依序：

1. `RETURN_TO_BEAR` / `RETURN_TO_BULL`
2. `MA_RETEST_REBOUND` / `MA_RETEST_REJECTION`
3. `SIDEWAYS`
4. `TREND_CONTINUATION_AWAY`
5. 否則繼續觀察

理由：

- 正式 opposite clear close優先於箱型背景。
- Retest range-touch加正確側收盤，是直接的回測反應。
- 使用者定義 Trend Continuation 是「不屬於前三類」的結果，因此排在 Sideways 之後。
- 每個 event只允許一個 terminal class。

Study end尚未命中：

```text
RIGHT_CENSORED
```

---

## 17. Long/Short mirror

| 元素 | Long | Short |
|---|---|---|
| Day1 | Close ≥ MA×1.002 | Close ≤ MA×0.998 |
| Rearm | Close ≤ MA | Close ≥ MA |
| Day2成功 | Close2 > Close1 | Close2 < Close1 |
| Reference E | MA(D1-1)×1.01 | MA(D1-1)×0.99 |
| 3% target | E×1.03 | E×0.97 |
| ATR target | E+kATR | E−kATR |
| Dynamic stop | MA(u-1)×0.985 | MA(u-1)×1.015 |
| Retest response | touch且Close>MA | touch且Close<MA |
| Opposite return | Close≤MA×0.998 | Close≥MA×1.002 |
| Trend away | Close≥MA×1.002 | Close≤MA×0.998 |

Long與Short不得合併成同一 probability denominator。

---

## 18. Entanglement filter

每個 Day1保存三個 causal snapshots：

```text
box_active_at_session_start
box_formed_on_day1_close
box_active_after_day1_close
```

Binary cohort：

```text
ENTANGLED_AT_SIGNAL
= box_active_at_session_start
  OR box_formed_on_day1_close

CLEAN_AT_SIGNAL
= otherwise
```

若 Day1 是從一個 session-start active box突破，仍屬 entangled context，即使該 close令 box invalidated。

不得使用 D1之後形成的 box回頭分類 Day1。

UI modes：

```text
ALL
EXCLUDE_ENTANGLED
ONLY_ENTANGLED
SPLIT_ENTANGLED_CLEAN
```

---

## 19. Censoring

### Day2

沒有下一有效 trading bar：

```text
DAY2_NOT_EVALUABLE
```

不進 Two-Day denominator，也不進 Day2-failure path。

### Target

Study end時 target與stop均未命中：

```text
RIGHT_CENSORED
```

不算失敗。

### Failure path

Study end仍無terminal outcome：

```text
RIGHT_CENSORED
```

不自動歸為 Trend Continuation。

每項統計必須保存：

```text
eligible_count
resolved_count
success_count
censored_count
not_evaluable_count
```

---

## 20. Event schema

每個 Day1 immutable event至少保存：

- Identity：event ID、study ID、ticker、period、direction。
- Data：provider、coverage、fingerprint。
- Definition：spec revision/hash、breakout definition revision。
- D1：date、OHLCV、MA(t)、MA(t-1)、ATR14(t)。
- Breakout：distance percent、ATR distance、latch before/after。
- Reference：entry level、observation start。
- Volume：current、previous、change、三個nested flags、evaluable state。
- Entanglement：session-start、formed-on-D1、post-close、binary cohort、box ID。
- D2：date、close、evaluable、success/failure。
- Censor state。
- Event audit cutoff：每個決定可使用資料的最後日期。

`dynamic_stop_history` 不應放在單一不可查詢 blob；應由 target outcome session audit或normalized stop history保存。

---

## 21. Aggregate schema

Aggregate key至少包含：

```text
study_id
sma_period
direction
entanglement_cohort
condition_type
volume_threshold
target_type 或 failure_outcome
```

保存：

```text
eligible_count
resolved_count
success_count
censored_count
not_evaluable_count
probability
wilson_lower
wilson_upper
low_sample_warning
```

另建 membership/drilldown relation：

```text
aggregate_id
event_id
membership_role:
ELIGIBLE / RESOLVED / NUMERATOR / CENSORED
```

任何 `38/60` 都能展開查出60筆 denominator與38筆 numerator。

---

## 22. Wilson CI

使用 two-sided Wilson score 95% interval：

```text
z = 1.959963984540054
p = k/n

center =
(p + z²/(2n)) / (1 + z²/n)

half =
z × sqrt(p(1-p)/n + z²/(4n²))
    / (1 + z²/n)
```

輸出：

```text
[center-half, center+half]
```

若 `n=0`：

```text
probability = null
CI = null
status = NOT_EVALUABLE
```

若 `n<20`：

```text
LOW_SAMPLE_SIZE = true
```

---

## 23. Frontend output

獨立頁面建議：

```text
/ma-breakout-analytics
```

輸入：

- Ticker
- Selected SMA
- Nearby range / step
- Date range
- Direction mode
- Entanglement mode

輸出順序：

1. Breakout event count
2. Two-Day success
3. Volume ≥10/20/30
4. Two-Day × volume
5. Target-before-stop matrix
6. Day2-failure outcome table
7. Combined「回測／轉向／橫盤」
8. Nearby period comparison
9. Event drilldown
10. Chart

必須清楚標示：

```text
統計基準進場價；不是實際策略成交價。
```

不得提供：

- best MA
- ranking
- composite score
- strategy PnL
- trade recommendation

---

## 24. Chart overlay

Chart payload由backend提供 authoritative values；frontend不得重算。

顯示：

- Candles
- SMA(t)
- Day1 marker
- Long/Short ±0.2% threshold
- Day2 marker與結果
- Reference entry
- 每個target level
- Dynamic MA stop staircase
- MA retest ±0.1% zone
- failure terminal outcome
- Visual box/entanglement context
- volume change
- censor marker

Target drilldown一次選一個 target，避免六條target與stop同時造成圖面過度擁擠。

---

## 25. API

Dedicated namespace：

```text
POST /api/ma-analytics/studies
GET  /api/ma-analytics/studies/{id}
GET  /api/ma-analytics/studies/{id}/summary
GET  /api/ma-analytics/studies/{id}/events
GET  /api/ma-analytics/studies/{id}/events/{event_id}
GET  /api/ma-analytics/studies/{id}/targets
GET  /api/ma-analytics/studies/{id}/failure-paths
GET  /api/ma-analytics/studies/{id}/aggregates/{aggregate_id}/members
GET  /api/ma-analytics/studies/{id}/chart/{period}
GET  /api/ma-analytics/studies/{id}/export
```

Study lifecycle：

```text
RUNNING
COMPLETED
FAILED
```

支援 direction、entanglement、period、condition、target、volume threshold與censor status filters。

---

## 26. Persistence

獨立 additive schema：

```text
ma_breakout_analytics_studies
ma_breakout_analytics_events
ma_breakout_target_outcomes
ma_breakout_target_session_audit
ma_breakout_failure_outcomes
ma_breakout_aggregates
ma_breakout_aggregate_members
```

每個study保存：

- analytics revision
- spec hash
- config hash
- data fingerprint
- provider
- coverage
- requested periods
- frozen definitions
- status/error

每個 event × target 一筆 outcome，不能用單一 `target_or_stop_first` 欄位代表所有targets。

不得讀寫或migration rewrite：

- MA_BOX Rev3 tables
- Simple/Advanced history
- optimization cache
- MA_BOX event ledger

---

## 27. Test matrix

原始51項全部保留：

1. Tiny cross不建event  
2. Long valid Day1  
3. Short valid Day1  
4. Same-side不重複  
5. Opposite-side rearm  
6–9. Long/Short Day2 success/failure  
10–12. Volume恰為10/20/30  
13. +35%同屬三個門檻  
14. +15%僅GE10  
15. Invalid previous volume  
16. Long reference = previous MA×1.01  
17. Reference entry不定義Day1  
18–24. +3%與五種ATR target/stop順序  
25–26. Green/Red同日target+stop  
27. Target right censor  
28. Dynamic stop每日更新  
29. ATR snapshot固定  
30. ±0.1% zone intersection  
31. Retest terminal  
32. Return terminal  
33. Sideways terminal  
34. Trend terminal  
35. 無fixed follow-up horizon  
36. Terminal互斥  
37. Combined count等於前三類加總  
38. Failure right censor不進denominator  
39–41. Failure outcomes × GE10/20/30  
42. Long/Short isolation  
43. Entanglement causal classification  
44. Clean classification  
45. Nearby SMA isolation  
46. Wilson CI  
47. Low-N warning  
48. Numerator drilldown  
49. Denominator drilldown  
50. MA_BOX Rev3 no mutation  
51. Legacy regression unchanged  

新增本次凍結決策的direct tests：

52. Day1使用completed MA(t)，不是MA(t-1)  
53. Day1只在close確認；High-only不成立  
54. Post-event grey zone不rearm  
55. Raw opposite-side completed close才rearm  
56. Study開始無prior latch時不得創造事件  
57. Target observer最早從D2 Open開始  
58. Day1 intraday target不得回填  
59. Long/Short open-gap target/stop mirror  
60. Return使用opposite ±0.2%  
61. Trend away使用same-side ±0.2%  
62. Return優先於Sideways  
63. Retest優先於Sideways  
64. Sideways優先於Trend  
65. Frozen VisualBoxObserver使用Rev2 qualifying formation bars  
66. ATR invalid只排除ATR target，不排除+3% target  
67. D2與volume joint denominator要求兩者均evaluable  
68. Target outcomes按target獨立  
69. Entanglement formed after Day1不得回畫  
70. Short E=MA(D1-1)×0.99  
71. Short stop=MA(u-1)×1.015  
72. Config/schema不存在target timeout或failure timeout

所有 correctness tests使用deterministic synthetic OHLCV；真股票資料不能作唯一正確性證據。

---

## 28. Remaining ambiguities

六項 blocking decisions均已凍結：

| 決策 | Frozen result |
|---|---|
| A Day1 threshold | completed Close相對MA(t) ±0.2% |
| B Trend away | follow-up completed Close達同方向±0.2% |
| C Return | completed Close達反方向±0.2% |
| D Sideways | frozen MA_BOX causal visual-box semantics |
| E Precedence | Return → Retest → Sideways → Trend |
| F Short mirror | entry MA(D1-1)×0.99；stop MA(t-1)×1.015 |

另外凍結：

- Two-Day = strict Close-over-Close。
- D2 failure observation從D3開始。
- Target/stop observation從D2 Open開始。
- ATR target snapshot = completed ATR14(D1)。
- Reference entry不要求實際成交。
- 所有targets無固定horizon。
- Long/Short denominator永不混合。
- Sideways四根結構是minimum confirmation，不是timeout。

目前沒有會改變分析結果的 remaining ambiguity。

尚待使用者核准後才可進行的非語意工作：

- 建立正式immutable spec artifact及SHA-256
- persistence migration
- backend/frontend implementation
- implementation handoff

**本輪未實作、未修改任何檔案。**

MA_BREAKOUT_ANALYTICS_V1 SPEC READY FOR USER REVIEW

MA_BREAKOUT_ANALYTICS_V1 REVISION 2  
MASTER SPEC REVIEW COMPLETE
<!-- END SOURCE A -->

<!-- BEGIN SOURCE B: AUTHORITATIVE SOL FROZEN REVISION 3 AMENDMENT -->
## 1. Revised Sideways definition

`SIDEWAYS` 與 `ENTANGLEMENT` 正式拆開。

Entanglement 繼續完全沿用 MA_BOX_LONG_V1 Rev3 causal box semantics，但只用於 cohort filter：

```text
ALL
EXCLUDE_ENTANGLED
ONLY_ENTANGLED
SPLIT_ENTANGLED_CLEAN
```

Sideways 改為獨立的 causal price-consolidation rule，不要求：

- K線穿越 MA
- Close 在 MA 兩側切換
- 價格靠近 MA
- MA_BOX formation成立

對 Day2 failure event，從 D3 起收集 completed follow-up bars。令候選窗口結束日為 `u`：

```text
Window(u) = 最近4根 completed follow-up bars
```

四根必須全部晚於 D2，不得混入 D1、D2或更早 bars。

```text
WindowRange
= max(High in Window)
- min(Low in Window)

SidewaysATR
= Wilder ATR14(
    Window第一根之前的completed session
  )

NormalizedRange
= WindowRange / SidewaysATR
```

若：

```text
NormalizedRange <= 1.5
```

且同日沒有先成立：

```text
RETURN_TO_BEAR / RETURN_TO_BULL
MA_RETEST_REBOUND / MA_RETEST_REJECTION
TREND_CONTINUATION_AWAY
```

則：

```text
SIDEWAYS
```

ATR必須 finite 且 `>0`。無有效ATR時，該窗口不可評估，但event繼續等待後續窗口，不算failure或censor。

四根是 minimum confirmation structure，不是maximum observation horizon。Day2 failure仍持續觀察至terminal outcome或study end。

---

## 2. Sideways parameter comparison and frozen choice

### Window length

| 候選 | 優點 | 主要問題 |
|---|---|---|
| 4 bars | 能辨識短而清楚的整理；較快形成causal判定；與日線人工觀察節奏一致 | 比5 bars稍容易出現短暫假整理 |
| 5 bars | confirmation較強 | 容易把合理的短整理延後；期間可能先被其他terminal吸收 |

Frozen：

```text
sideways_confirmation_bars = 4
```

### Range threshold

| 門檻 | 判斷 |
|---|---|
| `<=1.0 ATR` | 對4日總High-Low過度嚴格，只保留極端壓縮 |
| `<=1.5 ATR` | 能排除一般波動，同時保留肉眼可見的窄幅整理 |
| `<=2.0 ATR` | 過度寬鬆，普通pullback或緩慢方向移動也可能被歸類Sideways |

Frozen：

```text
sideways_max_range_atr = 1.5
```

邊界採 inclusive：

```text
NormalizedRange == 1.5
=> SIDEWAYS eligible
```

### ATR reference

不採：

- 確認日ATR14：會讓同一窗口波動同時擴大分子與分母。
- Day2固定ATR：無固定follow-up horizon時可能長期失真。
- 窗口內平均ATR：會被正在分類的bars反向影響。

Frozen：

```text
ATR snapshot
= completed ATR14 immediately before each candidate window
```

每個rolling candidate window有自己的pre-window snapshot；窗口內不更新。

---

## 3. Revised Trend Continuation definition

使用者提出的 Day1 Close progress rule正式接受。

Long：

```text
Close(u) >= MA(u) × 1.002
AND
Close(u) > Close(D1)
```

Short：

```text
Close(u) <= MA(u) × 0.998
AND
Close(u) < Close(D1)
```

兩條都必須成立。

選擇 Day1 Close，而不是 Day1 High/Low，原因：

- Day1 breakout本身是completed-close event。
- Day1 High/Low容易受單一wick影響。
- 要求突破Day1 High/Low會把「延續」提高成「突破盤中極值」。
- Distance-from-MA expansion可能因MA移動而成立，即使價格沒有真正前進。
- Day1 Close條件簡單、causal、方向對稱，直接證明價格重新超越原突破收盤。

僅維持在 `MA±0.2%` 不再足以構成Trend Continuation。

### Revised terminal precedence

每個D3以後completed session依序：

1. `RETURN_TO_BEAR / RETURN_TO_BULL`
2. `MA_RETEST_REBOUND / MA_RETEST_REJECTION`
3. `TREND_CONTINUATION_AWAY`
4. `SIDEWAYS`
5. 否則繼續觀察

Retest優先於Trend：同一根大範圍K線若先測試MA區域並收復，人工語意屬於回測反彈。

Trend優先於Sideways：符合「Sideways只在尚未觸發Return、Retest、Trend Away時成立」。

---

## 4. Condition-aware target observation origins

Reference Entry不變：

```text
Long:
E = MA(D1-1) × 1.01

Short:
E = MA(D1-1) × 0.99
```

它仍是統計基準價，不是actual execution。

### POST_D1 origin

適用條件：

```text
BREAKOUT
VOL_GE_10
VOL_GE_20
VOL_GE_30
VOL_LT_10
```

因這些條件在D1 close後已知：

```text
observation_origin = POST_D1
first_evaluable_session = D2 Open
```

Dynamic stop第一日：

```text
Long:  MA(D1) × 0.985
Short: MA(D1) × 1.015
```

### POST_D2 origin

適用條件：

```text
DAY2_SUCCESS
DAY2_SUCCESS_AND_VOL_GE_10
DAY2_SUCCESS_AND_VOL_GE_20
DAY2_SUCCESS_AND_VOL_GE_30
```

因Day2 success在D2 completed close後才知道：

```text
observation_origin = POST_D2_SUCCESS
first_evaluable_session = D3 Open
```

Dynamic stop第一日：

```text
Long:  MA(D2) × 0.985
Short: MA(D2) × 1.015
```

Day2 intraday High、Low、Open不得參與POST_D2 target/stop判定。

同一 event與target可以因此產生兩筆不同 outcome：

```text
POST_D1 outcome
POST_D2_SUCCESS outcome
```

兩者不得互相覆寫或共用resolution date。

若Day2 success成立但study沒有D3：

```text
eligible = true
resolved = false
RIGHT_CENSORED_NO_POST_CONDITION_SESSION
```

---

## 5. 受影響 event schema

Day1 event新增或明確化：

```text
day1_close_reference_for_trend
trend_clear_side_met
trend_new_advance_met
trend_confirmation_date
```

Sideways欄位：

```text
sideways_confirmation_bars = 4
sideways_window_start
sideways_window_end
sideways_window_dates
sideways_window_high
sideways_window_low
sideways_range
sideways_atr_reference_date
sideways_atr14_snapshot
sideways_range_atr
sideways_threshold_atr = 1.5
sideways_confirmation_date
```

Entanglement欄位保留，但不得作為sideways判定來源：

```text
entanglement_status
box_active_at_session_start
box_formed_on_day1_close
box_active_after_day1_close
```

Target outcome schema必須新增：

```text
observation_origin:
POST_D1
POST_D2_SUCCESS

condition_known_date
observation_start_date
observation_start_session
first_dynamic_stop
resolution_date
resolution_state
```

Target outcome identity至少為：

```text
event_id
target_type
observation_origin
```

不得只以：

```text
event_id + target_type
```

作unique key。

Failure outcome新增：

```text
terminal_precedence_revision
sideways_definition_revision
trend_definition_revision
```

---

## 6. 受影響 aggregate schema

Aggregate key新增：

```text
observation_origin
```

Target aggregate不得混合：

```text
POST_D1
POST_D2_SUCCESS
```

正式對應：

| Condition | Required origin |
|---|---|
| Breakout | POST_D1 |
| Vol≥10/20/30 | POST_D1 |
| Day2 success | POST_D2_SUCCESS |
| Day2 success + Vol≥10/20/30 | POST_D2_SUCCESS |

每個aggregate繼續保存：

```text
eligible_count
resolved_count
success_count
censored_count
not_evaluable_count
probability
Wilson CI
event membership
```

Failure-path aggregate維持互斥分類，但更新precedence：

```text
Return
Retest
Trend
Sideways
Right-censored
```

前三個使用者關心的合計仍為：

```text
Retest
+ Return
+ Sideways
```

它們仍互斥，但不再代表terminal precedence順序。

Sideways aggregate另保存：

```text
window_bars = 4
range_atr_threshold = 1.5
atr_reference_mode = PRE_WINDOW_COMPLETED_ATR14
```

---

## 7. 受影響 test matrix

原有測試中以下項目必須修改：

- Test 33 `Sideways terminal`：改用獨立range compression，不得依賴MA crossing。
- Test 34 `Trend terminal`：必須同時驗證clear side及突破Day1 Close。
- Test 36 `Terminal mutually exclusive`：使用新precedence。
- Tests 39–41：volume-conditioned failure outcomes套用新Sideways與Trend規則。
- Test 43只驗證entanglement cohort，不再兼任Sideways測試。
- Test 64改為`Trend優先於Sideways`。
- 舊「Sideways使用VisualBoxObserver」測試刪除或改為cohort-only測試。

新增direct tests：

1. 四根completed follow-up bars才可Sideways。
2. 三根不得確認Sideways。
3. 五根不是必要條件；第四根已符合即可確認。
4. 四根全部必須晚於D2。
5. `range/ATR == 1.5`成立。
6. `range/ATR >1.5`不成立。
7. 使用window前一completed session的Wilder ATR14。
8. Window內ATR變化不得修改該window denominator。
9. Invalid pre-window ATR令該window不可評估，但observer繼續。
10. 價格全在MA上方仍可Sideways。
11. 價格全在MA下方仍可Sideways。
12. Sideways不要求K線穿MA。
13. `ENTANGLED=true、SIDEWAYS=false`可成立。
14. `ENTANGLED=false、SIDEWAYS=true`可成立。
15. Long僅clear above但`Close<=Close(D1)`不得Trend。
16. Long `Close>Close(D1)`但未clear above不得Trend。
17. Long兩條同時成立才Trend。
18. Long `Close==Close(D1)`不得Trend。
19. Short僅clear below但`Close>=Close(D1)`不得Trend。
20. Short兩條同時成立才Trend。
21. Day1 High/Low不參與Trend gate。
22. 同日Retest及Trend成立時選Retest。
23. 同日Trend及Sideways成立時選Trend。
24. POST_D1 Breakout target從D2 Open開始。
25. Volume-conditioned target從D2 Open開始。
26. POST_D2_SUCCESS target從D3 Open開始。
27. Day2+Volume target從D3 Open開始。
28. D2 intraday target hit不得回填POST_D2_SUCCESS outcome。
29. D2 intraday stop hit不得回填POST_D2_SUCCESS outcome。
30. 相同D2 hit可正常影響POST_D1 outcome。
31. POST_D2 long首個stop使用`MA(D2)×0.985`。
32. POST_D2 short首個stop使用`MA(D2)×1.015`。
33. 同一event/target可保存兩個observation origins。
34. POST_D1與POST_D2 aggregates不可混線。
35. Day2 success但無D3時right-censored，不算failure。
36. 無fixed Sideways timeout。
37. 無fixed Day2-failure observation timeout。
38. Entanglement cohort結果不受Sideways規則修改。

---

## 8. 是否仍有 ambiguity

沒有會改變分析結果的remaining ambiguity。

Frozen amendments：

```text
SIDEWAYS:
4 completed post-D2 bars
range <= 1.5 × pre-window completed Wilder ATR14
no MA-cross requirement

TREND CONTINUATION LONG:
Close >= MA×1.002
AND Close > Close(D1)

TREND CONTINUATION SHORT:
Close <= MA×0.998
AND Close < Close(D1)

POST_D1 targets:
start D2 Open

POST_D2_SUCCESS targets:
start D3 Open

Terminal precedence:
Return → Retest → Trend → Sideways
```

MA_BREAKOUT_ANALYTICS_V1 SPEC AMENDMENT ACCEPTED

MA_BREAKOUT_ANALYTICS_V1 SPEC FROZEN REVISION 3
<!-- END SOURCE B -->
