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
