# MA_BOX_LONG_V1 — Frozen Specification Revision 2

Status: FROZEN FOR IMPLEMENTATION
Revision: MA_BOX_LONG_V1_REVISION_2

This document is the immutable authority for the independent MA_BOX_LONG_V1
study. It must be serialized as UTF-8 and hashed byte-for-byte before any
historical study is run. Revision 2 overrides conflicting Revision 1 text.

## Scope and invariants

- Long only, daily OHLCV bars, SMA only, no shorting.
- This is an independent study namespace. Simple v2, Advanced v2 and
  Advanced + Day1Stop are not changed, relabeled, or added to their selector.
- Initial capital 100,000; position size 100%; commission 0.05%; slippage
  0.02%; force-close at the study end.
- The only formal exits are the canonical MA(t-1) * 0.985 stop and the
  force-close. There is no fixed profit target, partial TP, or extreme TP.
- Execution policy is OHLC_HEURISTIC only: green/flat bars use O-L-H-C and
  red bars use O-H-L-C. Conservative/adverse-first is not used.
- Existing canonical helpers are authoritative and must be reused.

## Canonical normal MA entry

For a session with reference MA M = SMA(t-1):

```text
LowerEntry = M * 1.01
UpperEntry = M * 1.015
```

The session is armed when Open >= LowerEntry or High >= LowerEntry. It fills
at UpperEntry when High >= UpperEntry. Open > UpperEntry is
ENTRY_ZONE_MISSED, including a later fallback. Open == UpperEntry is valid.
The raw fill is UpperEntry and the actual buy is raw * (1 + 0.0002).
Normal entry is same-session and never carries an armed state to the next day.

## Canonical MA stop

```text
Stop(t) = SMA(t-1) * 0.985
```

If Open <= Stop, raw sell fill is Open. Otherwise Low <= Stop fills at Stop.
Actual sell is raw * (1 - 0.0002). The canonical Portfolio and execution
helpers are reused without semantic changes.

## Evaluation and fair comparison

The requested nearby periods are selected SMA +/- nearby_range in step-sized
integer periods (clamped to the supported SMA range 2..500). The common
evaluation start is the later of the requested start date and the first day on
which every requested period has a valid SMA(t-1). MA_LONG_BASELINE,
MA_BOX_LONG_V1 and BUY_AND_HOLD use exactly that same start and end.

BUY_AND_HOLD buys at the evaluation-start Open and sells at the final session
Close using the same whole-share, commission and slippage rules.

## Entanglement and initial box

At completed day t inspect exactly t-3..t using completed SMA(i). A qualifying
candle satisfies Low(i) <= SMA(i) <= High(i). At least three of four must
qualify. Among qualifying candles there must be at least one Close > SMA and
one Close < SMA, and the chronological non-neutral sequence must switch sides
at least once. Equal closes are neutral and cannot provide side-switch proof.

When first confirmed at t close, emit MA_ENTANGLEMENT_START and create a box;
its effects begin on t+1. The initial box uses only qualifying formation bars:

```text
BoxHigh = max(qualifying High)
BoxLow  = min(qualifying Low)
InitialMidpoint = (BoxHigh + BoxLow) / 2
```

The nonqualifying fourth bar is excluded from boundaries, contacts and
midpoint. Existing long positions are not exited by box formation.

## Boundary contacts and tolerance

V1 uses ATR_NORMALIZED tolerance. ATR is completed Wilder ATR14. At box
creation the tolerance snapshot is 0.10 * ATR14(t), must be finite and > 0,
and remains fixed for the complete box lifecycle. If unavailable, no box is
created and BOX_FORMING_NOT_READY_ATR is emitted.

Upper candidates are High/Open/Close; Low is never an upper contact. Lower
candidates are Low/Open/Close; High is never a lower contact. Open/Close are
assigned using the frozen InitialMidpoint. Every eligible contact has weight 1.

Each contact is a seed. Same-side points within the frozen tolerance form a
cluster, whose level is the median; support is recomputed around that median.
The cluster must include at least two distinct trading bars. A new candidate
updates a boundary only when its contact count is strictly greater than the
current boundary support count. Ties resolve by distinct bars, lower MAD,
closest distance to the current boundary, then outward level (higher upper,
lower lower). BoxHigh must remain greater than BoxLow.

On each completed bar, test breakout/down-break against session-start
boundaries first. Only when neither occurs may that bar enter the contact pool
and update boundaries. The update is effective the next session and records
old/new values, tolerance, contacts and reason. Breakout bars never move the
boundary before being tested.

## Box, breakout and risk gate

BOX_ACTIVE blocks new NORMAL_MA_ENTRY, but does not exit an existing long.
An upward breakout is Close(t) > the session-start BoxHigh and creates a new
immutable breakout_attempt_id.

Revision 2 uses a two-stage direct-entry gate. Stage A uses the breakout
BoxHigh snapshot and the next-session canonical stop:

```text
Stop_next = SMA(t) * 0.985
BoxRiskDistance = (BoxHigh - Stop_next) / BoxHigh
```

Only 0 < BoxRiskDistance <= 0.05 reaches DIRECT_ENTRY_ELIGIBLE. Greater than
5% emits NO_ENTRY_BOX_RISK_GT_5 and waits for retest. Nonpositive risk emits
NO_ENTRY_BOX_RISK_NOT_POSITIVE and waits for retest. Breakout Close is not the
Stage A gate.

Stage B at t+1 Open uses ActualEntry = Open(t+1) * (1 + 0.0002) and the same
Stop_next. ActualEntry must exceed the stop and ActualRisk must be <= 5%.
Otherwise it emits NO_ENTRY_GAP_RISK_GT_5 or
NO_ENTRY_OPEN_AT_OR_BELOW_STOP and enters WAIT_RETEST. Commission is excluded
from risk distance.

## Retest and failed breakout

WAIT_RETEST has no fixed session timeout. At each completed close use this
exact priority:

1. Close < BoxLow -> BEAR_BOX_BREAK -> BOX_INVALIDATED.
2. Low <= SMA(t) and Close > SMA(t) -> MA_RETEST_TOUCH,
   MA_RETEST_REBOUND, RETEST_CONFIRMED.
3. Otherwise Close <= BoxHigh -> FAILED_BOX_BREAKOUT -> BOX_REACTIVATED ->
   BOX_ACTIVE; the old attempt ends and the next breakout gets a new attempt ID.
4. If all qualifying formation bars in a newly confirmed entanglement are
   later than the original breakout date, supersede the old box with a new box
   lifecycle and new box/attempt context.
5. Otherwise remain WAIT_RETEST.

Retest execution is t+1 Open only, with canonical buy slippage and the same
5% actual-risk gate. A failed direct/retest risk check remains WAIT_RETEST.
No retest fill may use the signal day's Low, MA or Close.

## Long lifecycle and down breaks

Successful direct or retest entry consumes the box. A down box break never
opens a short. If a long exists, it remains managed only by the canonical MA
stop. After box invalidation or a completed position, a new box requires four
new completed formation bars; old bars cannot immediately recreate a box.

## State axes

Position state is FLAT or LONG_POSITION. Setup state is one of
TREND_ELIGIBLE, BOX_FORMING, BOX_ACTIVE, BREAKOUT_CONFIRMED,
DIRECT_ENTRY_ELIGIBLE, WAIT_RETEST, RETEST_CONFIRMED, FAILED_BREAKOUT,
BEAR_BOX_BREAK and BOX_INVALIDATED. The axes are orthogonal, so
LONG_POSITION + BOX_ACTIVE is valid.

## Baseline and counterfactual

Each period independently runs MA_LONG_BASELINE with the canonical normal
entry and stop and no box logic. Any baseline entry blocked while the box run
is flat and BOX_ACTIVE becomes a shadow/counterfactual trade whose entire
lifecycle, costs, MFE/MAE and PnL exactly match baseline. Shadow capital never
enters the Box equity curve.

## Audit, persistence and UI contract

Every event records date/phase, visual SMA(t), execution SMA(t-1), OHLC,
states, box/attempt/position IDs, boundaries before/after, tolerance, contacts,
stop, planned and actual prices, risk values, quantity, commission, slippage,
reason code and information cutoff. Results are stored in additive
ma_box_studies, ma_box_runs, ma_box_events and
ma_box_counterfactual_trades tables. Existing rows are untouched.

The dedicated /ma-box page displays period comparisons, baseline/box/B&H,
nearby switching, complete daily candles, SMA, boxes, boundaries, events,
entries, exits, active stop and holding intervals. Export is full-period chart
data plus audit JSON and trade CSV/JSON where supported.

## Stable reason codes

NORMAL_MA_ENTRY, MA_STOP_EXIT, MA_ENTANGLEMENT_START, BOX_ACTIVE,
BOX_BOUNDARY_UPDATE, BOX_UP_BREAKOUT, BOX_DOWN_BREAK,
BOX_DIRECT_BREAKOUT_ENTRY, NO_ENTRY_BOX_RISK_GT_5,
NO_ENTRY_BOX_RISK_NOT_POSITIVE, NO_ENTRY_GAP_RISK_GT_5,
NO_ENTRY_OPEN_AT_OR_BELOW_STOP, WAIT_RETEST, MA_RETEST_TOUCH,
MA_RETEST_REBOUND, BOX_BREAKOUT_RETEST_ENTRY, FAILED_BOX_BREAKOUT,
BOX_REACTIVATED, BOX_INVALIDATED, FILTERED_BY_BOX, COUNTERFACTUAL_ENTRY,
COUNTERFACTUAL_EXIT, FORCED_END_OF_TEST_EXIT, BOX_FORMING_NOT_READY_ATR,
BOX_CONSUMED_BY_ENTRY, NO_ENTRY_ALREADY_LONG, STUDY_END_UNFILLED,
SUPERSEDED_BY_NEW_BOX.

Any change to these semantics is a new strategy/spec revision and must not
rewrite V1 historical results.
