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
