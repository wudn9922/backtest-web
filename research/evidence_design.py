"""Frozen PRE-V3 questions and evidence screens; no search or fitted cutoffs."""
from dataclasses import replace
from research.modules import FULL
from research.structural_study import CANDIDATES
from research.evidence_simulation import simulate

MA_VARIANTS = {
    'M0': ('ADVANCED_FULL', FULL, 'full'),
    'M1': ('NO_MA_BREAK_FAMILY', replace(FULL, ma_break=False), 'full'),
    'M2': ('HALF_STOP_ONLY_NO_BREAK_PROTECTION', FULL, 'half_only'),
    'M3': ('BREAK_PROTECTION_EXIT_OFF', FULL, 'exit_off'),
}
DEFINITIONS = {
    'M0': 'Unchanged full Advanced v2.',
    'M1': 'No MA half sale, BreakDayLow tracking, protection exit or reset; all other modules unchanged.',
    'M2': 'Before First TP, at most one current-quantity half sale per daily bar at the MA stop. No episode tracking or reset; eligible again the next trading day even if price stays below the updated stop. Keep validation flags and original post-TP regime. This changes repeated-risk eligibility as well as removing protection, so it is NOT a pure single-event causal contrast.',
    'M3': 'Keep half sale, episode tracking, suppression of repeated halves within an episode, and original close-only MA(t) reset. Never sell because BreakDayLow is broken; do not include that disabled exit in risk/profit ordering. First TP, protective, validations unchanged.',
}
BOOTSTRAP = {'replicates': 4000, 'seed': 20260904, 'confidence': .95,
    'episode': 'Synchronized calendar half-year of entry (Jan-Jun / Jul-Dec), shared across all symbols.',
    'primary': 'Two-way pigeonhole resampling: independently sample 11 ticker clusters and observed half-year episode clusters with replacement, multiply their counts for each anchor. Reuse each anchor weight across candidates. Analyze each policy separately; never pool periods or policies as observations.',
    'sensitivity': 'Ticker-only cluster bootstrap and equal-ticker-weighted mean, alongside pooled-entry-weighted mean and median.',
    'limitations': '11 ticker clusters and 11 partly observed calendar episodes; approximate descriptive percentile intervals, not exact coverage or confirmatory significance. Lifecycles overlapping episode boundaries remain dependent; episode blocking is not a complete dependence model.'}
FEATURES = {
    'atr_pct': 'ATR(t-1) / actual entry execution price.',
    'ma20_slope': 'MA20(t-1)/MA20(t-6)-1 (5 completed trading-day slope).',
    'distance_ma20': 'P0/MA20(t-1)-1; P0 known when entry fills. Entry-zone v2 makes this nearly constant; not an identifying regressor.',
    'prior20_return': 'Close(t-1)/Close(t-21)-1.',
    'prior60_return': 'Close(t-1)/Close(t-61)-1.',
    'rv20': 'Sample standard deviation of last 20 completed daily simple returns * sqrt(252).',
    'rv60': 'Sample standard deviation of last 60 completed daily simple returns * sqrt(252).',
    'volume_ratio': 'Volume(t-1) / mean Volume(t-21 ... t-2). Entry-day volume is NEVER used.',
    'spy_prior_trend': 'SPY Close(t-1)/Close(t-61)-1.',
    'qqq_prior_trend': 'QQQ Close(t-1)/Close(t-61)-1.',
    'spy_above_ma200': 'SPY Close(t-1) > SMA200(t-1); null without 200 completed bars.',
    'symbol_above_ma200': 'Symbol Close(t-1) > SMA200(t-1); null without 200 completed bars.',
}
MODEL_FEATURES = ('prior60_return', 'rv20', 'atr_pct', 'ma20_slope', 'volume_ratio', 'spy_prior_trend')
MODEL = {'features': MODEL_FEATURES, 'form': 'OLS with ticker fixed effects; prespecified six features standardized by within-ticker SD. Two-way cluster bootstrap coefficient intervals (499 replicates); Huber IRLS point estimates as sensitivity.',
    'not_estimated': 'ETF indicator is exactly collinear with ticker effects. Distance from MA20 is structurally almost constant. Other recorded features retained for description, not searched for model fit.',
    'purpose': 'Associations only, no feature selection, thresholds, predictions, p-value discovery or out-of-sample claims.'}
GATE = {
    'majority': 'At least 6/11 improve Return and at least 6/11 improve Sharpe under EACH full-period policy.',
    'period': 'At least 4/6 subperiod-policy cells have positive cross-symbol median Return AND Sharpe deltas, with at least one passing policy in EACH subperiod.',
    'policy': 'Full-period median Return AND Sharpe delta positive under all 3 policies; return-improved breadth spread at most 3 symbols.',
    'drawdown': 'In EACH policy, median MDD delta >= -3 pp and cross-symbol 10th percentile MDD delta >= -10 pp.',
    'matched': 'In at least 2 policies, mean matched entry-cost return delta > 0 both after removing NVDA/META and after removing each symbol largest Full winner.',
    'concentration': 'In at least 2 policies, top 3 positive trade deltas <= 50% of sum positive matched dollar deltas, AND non-NVDA/META dollar delta > 0.',
    'uncertainty': 'Primary two-way bootstrap mean interval lower bound > 0 in at least 2 policies required for STRONG; not mandatory for exploratory walk-forward.',
    'ready': 'All first six screens pass; at most two candidates. This authorizes only prospective validation design, NOT production v3 or investment.',
    'grade': 'STRONG = all seven; MODERATE = first six or at least 4/6 first screens; WEAK = at least one positive full-period median return with fewer screens; REJECT = no positive full-period median return. Benchmark = reference, not a new candidate.',
    'prespecification': 'Screens written before running the new MA and matched-entry study. They are explicit engineering/research judgments, not universal risk preferences. No optimization performed.'}

def run_candidate(key, prepared, **kwargs):
    if key in CANDIDATES:
        c = CANDIDATES[key]
        return simulate(prepared, c.modules, first_tp_fraction=c.first_tp_fraction, **kwargs)
    _, modules, mode = MA_VARIANTS[key]
    return simulate(prepared, modules, ma_mode=mode, **kwargs)
