"""Frozen before M3 retrospective walk-forward computation. No tuning hooks."""
from datetime import date, timedelta

POLICIES=('conservative','ohlc_heuristic','favorable')
SYMBOLS=('NVDA','AAPL','MSFT','GOOGL','AMZN','META','TSLA','AMD','AVGO','SPY','QQQ')
TESTS=(
 ('F1',date(2023,9,1),date(2024,2,29)),
 ('F2',date(2024,3,1),date(2024,8,31)),
 ('F3',date(2024,9,1),date(2025,2,28)),
 ('F4',date(2025,3,1),date(2025,8,31)),
 ('F5',date(2025,9,1),date(2026,2,28)),
 ('F6',date(2026,3,1),date(2026,9,1)),
)

def folds():
    rows=[]
    for name,start,end in TESTS:
        train_end=start-timedelta(days=1)
        rows.append({'design':'expanding','fold':name,'train_start':date(2021,9,1),'train_end':train_end,'test_start':start,'test_end':end})
        rows.append({'design':'rolling','fold':name,'train_start':date(start.year-2,start.month,start.day),'train_end':train_end,'test_start':start,'test_end':end})
    return rows

M3_SEMANTICS={
 'base':'Advanced Strategy Version 2, daily OHLC, single long position, whole shares.',
 'unchanged':['Entry Zone v2','Volume confirmation vs previous trading day','Day2 close strictly greater than Day1 close','MA(t-1) half-stop and sell floor(current_qty/2), minimum one','BreakDayLow recording','BREAK_PROTECTION episode','Low(t) > MA(t) close-only reset; normal MA risk resumes next session','First TP','Protective Stop','Bias/ATR independent extreme TP','20% Q0 partial-sale rule','gap, costs, slippage and selected intrabar policy'],
 'only_change':'While BREAK_PROTECTION is active, Low < BreakDayLow records no full exit. Tracking and the existing MA(t) close-reset lifecycle remain active.',
 'forbidden':['parameter change','candidate switch','new signal','production registration','test-informed gate change'],
}
PARAMETER_FREEZE={'source':'canonical Advanced backtest f341e6a5-f7d4-4e72-b6a1-18ba09f71974','all_fields':'Copied byte-for-value from canonical request; no field-level override except ticker, dates and execution_policy required by the design.'}
FOLD_EXECUTION={
 'train':'Fresh-capital, flat-at-window-start portfolio; full prior cache is available only for indicator warm-up. Train never chooses parameters or changes M3.',
 'test':'Fresh-capital, flat-at-test-start portfolio with completed pre-test indicator warm-up. Train positions, PnL and capital never enter test. This is a boundary-reset research design, not a claim about live continuity.',
 'same_test_twice':'Expanding and rolling share identical test boundaries and therefore identical raw test results. They differ only in the chronological train evidence and whether the frozen deployment gate passes.',
 'cagr':'Reported for API consistency but annualizing a six-month sample is unstable and not a primary decision metric.',
}
TRAIN_GATE={
 'scope':'Computed independently per train fold and intrabar policy using 11 symbols.',
 'return_breadth':'Strict majority: at least 6/11 symbols have M3 − v2 Return >= 0 (ties count as non-harm).',
 'return_median':'Cross-symbol median Return delta strictly > 0.',
 'mdd':'Cross-symbol median MDD delta >= -3 percentage points; positive delta means M3 drawdown is less severe.',
 'concentration':'Largest positive symbol Return delta / sum of positive deltas <= 50%; no positives fails.',
 'fold_gate':'PASS only if Conservative passes and at least two of three policies pass all four checks.',
 'use':'A PASS means the retrospective deployment simulation selects M3 for that next test fold; FAIL selects v2. Test is always computed for audit and never changes the gate.',
}
BREAKDOWN_CRITERIA={
 'clock':'Sessions after the v2 BreakDayLow exit; event day is session 0. Prices are underlying daily data, not M3 signals.',
 'false_breakdown':'At least 20 forward sessions available; any close during sessions 1..10 >= original BreakDayLow AND session-20 close return from v2 execution price >= 0%.',
 'true_breakdown':'At least 20 forward sessions available; no close during sessions 1..10 >= original BreakDayLow AND (session-20 return <= -5% OR minimum Low through session 20 return <= -10%).',
 'mixed':'Every other path, including conflicting recovery/drawdown evidence or an incomplete 20-session horizon.',
 'fixed_note':'The 10/20-session and 5%/10% descriptive thresholds are frozen before computation; they are not strategy conditions and are never optimized.',
}
REGIME_CRITERIA={
 'trend':'Using SPY test-period close only: uptrend if start-to-end return > +5%; downtrend if < -5%; otherwise sideways.',
 'volatility':'SPY test-period completed daily returns annualized: high >=25%; low <15%; otherwise medium.',
 'use':'Descriptive labels only. No entry, gate, candidate or parameter uses them.',
}
RETROSPECTIVE_DECISION={
 'direction':'At least 2/3 policies have positive median fold-level Return delta in >=4/6 folds; aggregate Return-improved symbol-fold cells >= half in those policies.',
 'train_gate':'At least one design passes its train gate for >=3/6 folds.',
 'dependence':'Two-way symbol×fold bootstrap mean Return-delta interval may cross zero for PROMISING, but STRONG requires lower bound >0 in >=2 policies.',
 'tail':'PROMISING requires matched BreakDayLow 5th-percentile entry-cost delta >= -10 pp and worst additional marked drawdown >= -20 pp.',
 'leave_one_out':'At least 8/11 holdouts retain positive median Return delta in >=2 policies, and results are not supported only when NVDA/META/TSLA are present.',
 'earlier':'STRONG requires a valid common earlier check with at least 3 calendar years and 500 usable sessions per symbol, plus supportive direction. If unavailable or shorter, STRONG is impossible.',
 'labels':'NOT SUPPORTED if core direction, train-gate, tail, or leave-one-out fails. PROMISING — NEEDS TRUE FORWARD DATA if they pass but any STRONG requirement fails. STRONG RETROSPECTIVE EVIDENCE — FREEZE AND FORWARD TEST only if all requirements including earlier check and bootstrap precision pass.',
}
EARLIER_CHECK={
 'preferred':'2016-01-01 through 2021-08-31 on one consistent adjustment basis.',
 'network_probe':'2026-09-05 query2 Yahoo HTTPS IPv4 returned curl error 7 before any data request completed; no proxy, tunnel, bypass, provider/code change, or repeated download was attempted.',
 'cache':'Frozen common cache begins 2020-12-03. Use only the common fully warmed interval ending 2021-08-31 as a transparent limited check.',
 'minimum_validity':'At least 3 calendar years and 500 usable sessions per symbol; otherwise report metrics but classify earlier evidence as unavailable for STRONG.',
}
FORWARD_FAILURE_CRITERIA=[
 'Conservative Return breadth below 50% for two consecutive six-month evaluation windows.',
 'Median MDD deterioration worse than 5 percentage points in any rolling 12-month review, or any M3 sleeve suffers >20 pp additional marked drawdown relative to v2 after a waived BreakDayLow exit.',
 'Matched waived-break exits have negative cumulative normalized delta and at least 30% classify TRUE BREAKDOWN once 20 or more eligible events exist.',
 'NVDA plus META contribute over 60% of positive normalized improvement for two consecutive annual reviews.',
 'Both SPY and QQQ have lower Return and Sharpe than v2 in three consecutive six-month windows.',
 'Conservative and Favorable Return-delta directions oppose each other for two consecutive windows.',
 'Any execution, accounting, look-ahead, data-adjustment, or audit parity failure invalidates the experiment immediately.',
]
