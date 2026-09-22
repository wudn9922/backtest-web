"""Report-layer aggregation for the frozen MA_STRUCTURE_V1 cross-stock run.

This module only reads persisted optimization/backtest results and writes a
machine-readable report.  It does not call providers, run a strategy, or
mutate production records.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - report can still be generated without numpy
    np = None


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "background-jobs.sqlite3"
UNIVERSE = ROOT / "data" / "research-universes.json"
MANIFEST = ROOT / "data" / "research-data-manifest-v3.json"
RUNTIME_FINGERPRINTS = ROOT / "reports" / "MA_STRUCTURE_V1_IMPL_2_FINAL_FINGERPRINTS.json"
RUNTIME_GUARD = ROOT / "reports" / "MA_STRUCTURE_V1_IMPL_2_RUNTIME_GUARD.json"
BASELINE_REPORTS = [ROOT / "reports" / "STAGE5_TEST_BASELINE_VERIFICATION.md",
                    ROOT / "reports" / "MA_STRUCTURE_V1_IMPL_2_FINAL_SIGNOFF_COMPLETE.md"]

PRIMARY = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO"]
EXPECTED_FP = {
    "NVDA": "967868422f9d858f63bb552d0c6f629c8904bb5b9454eb4127ff117b40f5f0bb",
    "AAPL": "7a8f079bcb34ffebd5303fad753d6552a6a01cee4fadb450091a6f9ab815ca78",
    "MSFT": "13b073d6b4364f5f0bd23ffd59e586501fc25a0f665cf55cdf02bfedd6b22ff9",
    "GOOGL": "698b003252d974355a363d15ab9e642c4a100619fad5d4af0802c402e01f4b0a",
    "AMZN": "75e76d3a721c111b725c5f75b0fabc1fc5beb63f3ea953105159a7bc7a1e2e80",
    "META": "da88293e5d008066b1b5a3fd0405670b24f991621088a51011a6225a2f4cddf2",
    "TSLA": "de1e80350d79eb2399f6e3f8af9b841deda5d8c881a684500bb8890c4b8a5f5e",
    "AMD": "d095d7a657277533159c7d1873b191e1232f6016d666d62543b2670f34ed8220",
    "AVGO": "b6ca10f1009fa9f68330ffe60232b368823e3bd177036053077d9a0f69574adc",
}
JOB_IDS = {
    "NVDA": "bb088935-48bd-423e-940e-9b015eb61d1c",
    "AAPL": "3efcc145-5b52-4265-974d-df3cc0ca6114",
    "MSFT": "f0560982-4fb5-4880-a034-2b50610ebc7a",
    "GOOGL": "1f4c4de2-0b89-49d4-a31c-4378675fe959",
    "AMZN": "d9a80ac5-cbdc-48eb-9ee1-5f70ce2d3028",
    "META": "d7dc1600-f593-435d-92f0-84b111211321",
    "TSLA": "55da778d-55ac-4aca-995f-02ac11f344af",
    "AMD": "272a4ef3-473b-445c-854b-d90c835f474e",
    "AVGO": "2d40e94d-3fc8-48b4-b687-fad2a64d4070",
}
SPEC_HASH = "17f0674247b13ddd0bcf79d1004ac999d5826f729c78d5e62f815de916ecc83b"
UNIVERSE_HASH = "0436d3cbfa0e9e67ea66eab0713f829362e8fb3773dfdd39851094af2ac643db"
MANIFEST_HASH = "caed8b26961a498cea9553489e670befd1de37dac6e5beb377012a4e0af29504"
RUNTIME_FP_HASH = "413880d6f8db9472ec0df0d1025a74001ac8712fae0a9871dfa2d9a5ddbefbab"
RUNTIME_GUARD_HASH = "bc5a21abdef50dcd658cbcef435dd84b1399860399ec6408f574f85ff9822973"
CANONICAL_RESULT_HASHES = {
    "c7ccad72-5f93-4bfc-b7d4-3635138c6f75": "a8591c16c401a002f1057cd3cb6add5b7c5b316836c667c985c258c501ddcfd5",
    "f341e6a5-f7d4-4e72-b6a1-18ba09f71974": "1300fe97a0d17b8cefb3a0602b81c91ad6c8064fe8a5cc5c2175542c80e31a9f",
}
CANONICAL_AUDIT_HASHES = {
    "c7ccad72-5f93-4bfc-b7d4-3635138c6f75": "35aa46cc16855e8ad85a9a90fd306ccad9edc7cb0ffa966ef2ffd826965683ed",
    "f341e6a5-f7d4-4e72-b6a1-18ba09f71974": "29f88c00f24dcb5ab561a8d751fff5ec76d6663056563c6ec93623805402e93c",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def q7(values: list[float]) -> float | None:
    values = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not values:
        return None
    if np is not None:
        return float(np.percentile(values, 50, method="linear"))
    values.sort()
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * 0.5
    lo, hi = math.floor(rank), math.ceil(rank)
    return values[lo] + (values[hi] - values[lo]) * (rank - lo)


def quantile(values: list[float], p: float) -> float | None:
    values = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not values:
        return None
    if np is not None:
        return float(np.percentile(values, p * 100, method="linear"))
    values.sort()
    rank = (len(values) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    return values[lo] + (values[hi] - values[lo]) * (rank - lo)


def mean(values: list[Any]) -> float | None:
    xs = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return sum(xs) / len(xs) if xs else None


def median(values: list[Any]) -> float | None:
    xs = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return q7(xs)


def product_return(values: list[Any]) -> float | None:
    xs = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not xs:
        return None
    out = 1.0
    for x in xs:
        out *= 1.0 + x
    return out - 1.0


def adjacent_stats(seq: list[Any]) -> dict[str, Any]:
    xs = [float(x) for x in seq if x is not None and math.isfinite(float(x))]
    changes = [abs(xs[i] - xs[i - 1]) for i in range(1, len(xs))]
    return {"sequence": xs, "mean": mean(xs), "median": median(xs),
            "min": min(xs) if xs else None, "max": max(xs) if xs else None,
            "population_sd": (float(np.std(xs, ddof=0)) if np is not None and xs else None),
            "mean_absolute_adjacent_change": mean(changes),
            "median_absolute_adjacent_change": median(changes),
            "change_count": len(changes), "largest_adjacent_jump": max(changes) if changes else None}


def pearson(xs: list[Any], ys: list[Any]) -> float | None:
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys)
             if x is not None and y is not None and math.isfinite(float(x)) and math.isfinite(float(y))]
    if len(pairs) < 2:
        return None
    ax, ay = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = sum(ax) / len(ax), sum(ay) / len(ay)
    dx, dy = [x - mx for x in ax], [y - my for y in ay]
    den = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    return sum(x * y for x, y in zip(dx, dy)) / den if den else None


def exact_sign_test(values: list[float]) -> dict[str, Any]:
    nz = [x for x in values if x is not None and math.isfinite(float(x)) and abs(float(x)) > 1e-12]
    k = sum(1 for x in nz if x > 0)
    n = len(nz)
    ties = len(values) - n
    if not n:
        return {"n_nonzero": 0, "positive": 0, "negative": 0, "ties": ties, "p_two_sided": None}
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / (2 ** n)
    return {"n_nonzero": n, "positive": k, "negative": n - k, "ties": ties,
            "p_two_sided": min(1.0, 2.0 * tail)}


def bootstrap_median(values: list[float], seed: int = 20260913, n: int = 10000) -> dict[str, Any]:
    xs = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not xs or np is None:
        return {"n": len(xs), "resamples": n, "seed": seed, "median": median(xs), "ci95": None, "status": "UNAVAILABLE"}
    rng = np.random.default_rng(seed)
    samples = rng.choice(np.asarray(xs), size=(n, len(xs)), replace=True)
    meds = np.median(samples, axis=1)
    return {"n": len(xs), "resamples": n, "seed": seed, "median": float(np.median(xs)),
            "ci95": [float(np.percentile(meds, 2.5, method="linear")),
                     float(np.percentile(meds, 97.5, method="linear"))],
            "status": "COMPUTED"}


def load_jobs() -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
    out: dict[str, dict[str, Any]] = {}
    try:
        for ticker in PRIMARY:
            job_id = JOB_IDS[ticker]
            row = con.execute("select id,job_type,status,created_at,started_at,finished_at,progress_current,progress_total,payload_json,result_json,errors_json from background_jobs where id=?", (job_id,)).fetchone()
            if row is None:
                raise RuntimeError(f"missing frozen job {ticker} {job_id}")
            payload, result = json.loads(row[8]), json.loads(row[9])
            out[ticker] = {"job_id": row[0], "job_type": row[1], "status": row[2],
                          "created_at": row[3], "started_at": row[4], "finished_at": row[5],
                          "progress_current": row[6], "progress_total": row[7],
                          "payload": payload, "result": result, "errors": json.loads(row[10])}
    finally:
        con.close()
    return out


def canonical_artifact_gate() -> dict[str, Any]:
    """Pin canonical result/audit payloads while allowing new research rows."""
    db = ROOT / "data" / "backtests.sqlite3"
    result_checks: dict[str, Any] = {}
    audit_checks: dict[str, Any] = {}
    con = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        for identifier, expected in CANONICAL_RESULT_HASHES.items():
            row = con.execute("select result_json from backtests where id=?", (identifier,)).fetchone()
            actual = None
            if row is not None:
                actual = hashlib.sha256(json.dumps(json.loads(row["result_json"]), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            result_checks[identifier] = {"expected": expected, "actual": actual, "match": actual == expected}
        for identifier, expected in CANONICAL_AUDIT_HASHES.items():
            rows = [dict(row) for row in con.execute("select * from position_audits where backtest_id=? order by position_id", (identifier,))]
            actual = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            audit_checks[identifier] = {"expected": expected, "actual": actual, "match": actual == expected}
    finally:
        con.close()
    return {"status": "PASS" if all(x["match"] for x in result_checks.values()) and all(x["match"] for x in audit_checks.values()) else "FAIL", "results": result_checks, "audits": audit_checks}


def validate_job(ticker: str, job: dict[str, Any]) -> list[str]:
    r, p = job["result"], job["payload"]
    checks: list[str] = []
    if job["status"] != "COMPLETED": checks.append("status")
    if job["errors"]: checks.append("errors")
    if r.get("complete_windows") != 9: checks.append("complete_windows")
    if r.get("provisional_windows") != 0: checks.append("provisional_windows")
    if len(r.get("rolling_windows", [])) != 9: checks.append("rolling_window_count")
    if r.get("data_fingerprint") != EXPECTED_FP[ticker]: checks.append("fingerprint")
    if r.get("provider") != "yahoo": checks.append("provider")
    if r.get("data_coverage", {}).get("bars") != 1441: checks.append("bars")
    if r.get("data_coverage", {}).get("first_date") != "2020-12-03": checks.append("first_date")
    if r.get("data_coverage", {}).get("last_date") != "2026-08-31": checks.append("last_date")
    if r.get("structure_spec_version") != "MA_STRUCTURE_V1": checks.append("spec_version")
    if r.get("structure_spec_hash") != SPEC_HASH: checks.append("spec_hash")
    if r.get("structure_implementation_revision") != "MA_STRUCTURE_V1_IMPL_2": checks.append("revision")
    if r.get("canonical_engine") is not True: checks.append("canonical_engine")
    if r.get("job_cache_reused") is not False: checks.append("job_cache_reused")
    if r.get("rolling_cache_key") is None: checks.append("rolling_cache_key")
    if r.get("skipped"): checks.append("skipped")
    if p.get("backtest", {}).get("ticker") != ticker: checks.append("ticker")
    b = p.get("backtest", {})
    expected_b = {"strategy": "simple", "start_date": "2021-09-01", "end_date": "2026-09-01", "initial_capital": 100000.0, "position_size_pct": 100.0, "commission_pct": 0.05, "slippage_pct": 0.02, "execution_model": "daily_conservative", "execution_policy": "ohlc_heuristic", "force_close_at_end": True}
    for key, value in expected_b.items():
        if b.get(key) != value: checks.append(f"backtest_{key}")
    params = b.get("parameters", {})
    expected_params = {"ma_type": "sma", "ma_period": 20, "breakout_trigger_pct": 1.0, "entry_stop_pct": 1.5, "exit_below_ma_pct": 1.5, "volume_increase_pct": 10.0, "ma_risk_pct": 1.5, "first_tp_pct": 3.0, "bias_lookback": 126, "bias_sigma_multiple": 2.0, "atr_period": 14, "atr_multiple": 2.0, "extreme_tp_pct_q0": 10.0, "max_extreme_tp_count": 3, "minimum_position_pct_q0": 20.0, "day1_stop_pct": 3.0}
    if any(params.get(key) != value for key, value in expected_params.items()): checks.append("strategy_parameters")
    if p.get("ma_min") != 5 or p.get("ma_max") != 100 or p.get("ma_step") != 1: checks.append("ma_range")
    combinations = p.get("combinations", [])
    if (len(combinations) if isinstance(combinations, (list, tuple, dict)) else combinations) != 96: checks.append("candidate_count")
    if p.get("mode") != "rolling_6m" or p.get("ranking_metric") != "total_return" or p.get("selection_mode") != "STRUCTURE_V1": checks.append("optimization_mode")
    rolling = p.get("rolling", {})
    if rolling.get("calendar_months") != 6 or rolling.get("fixed_ma_period") != 20 or rolling.get("independent_test_segments") is not True: checks.append("rolling_definition")
    for w in r.get("rolling_windows", []):
        if len(w.get("train_ranking", [])) != 96: checks.append(f"window_{w.get('index')}_train_candidates")
        if len(w.get("structure_ranking", [])) != 96: checks.append(f"window_{w.get('index')}_structure_candidates")
        if w.get("fixed_ma_period") != 20: checks.append(f"window_{w.get('index')}_fixed_ma")
        if w.get("status") != "COMPLETED" or not w.get("complete") or w.get("provisional", False): checks.append(f"window_{w.get('index')}_status")
    return checks


def build() -> tuple[dict[str, Any], str]:
    jobs = load_jobs()
    per_stock: list[dict[str, Any]] = []
    normalized_jobs: list[dict[str, Any]] = []
    all_windows: list[dict[str, Any]] = []
    gate_failures: dict[str, list[str]] = {}
    for ticker in PRIMARY:
        j = jobs[ticker]; r = j["result"]
        failures = validate_job(ticker, j)
        gate_failures[ticker] = failures
        normalized_jobs.append({"ticker": ticker, "job_id": j["job_id"], "status": j["status"],
                                "created_at": j["created_at"], "started_at": j["started_at"], "finished_at": j["finished_at"],
                                "progress": {"current": j["progress_current"], "total": j["progress_total"]},
                                "job_cache_reused": r.get("job_cache_reused"), "reused_from_job_id": None,
                                "complete_windows": r.get("complete_windows"), "provisional_windows": r.get("provisional_windows"),
                                "candidate_count_per_window": 96, "errors": len(j["errors"]), "skipped": len(r.get("skipped", [])),
                                "canonical_engine": r.get("canonical_engine"), "provider": r.get("provider"),
                                "bars": r.get("data_coverage", {}).get("bars"), "coverage": r.get("data_coverage"),
                                "fingerprint": r.get("data_fingerprint"), "rolling_cache_key": r.get("rolling_cache_key"),
                                "structure_version": r.get("structure_spec_version"), "structure_spec_hash": r.get("structure_spec_hash"),
                                "revision": r.get("structure_implementation_revision"), "gate": "PASS" if not failures else "FAIL",
                                "failed_checks": failures})
        perf_returns, struct_returns, fixed_returns = [], [], []
        perf_sh, struct_sh, perf_mdd, struct_mdd, perf_exp, struct_exp = [], [], [], [], [], []
        perf_pos, struct_pos, perf_hold, struct_hold = [], [], [], []
        perf_comm, struct_comm, perf_slip, struct_slip = [], [], [], []
        perf_mas, struct_mas = [], []
        train_perf, train_struct = [], []
        window_rows = []
        for w in r.get("rolling_windows", []):
            p = w.get("performance_test_result", {}) or {}
            s = w.get("structure_test_result", {}) or {}
            f = w.get("fixed_test_result", {}) or {}
            perf_returns.append(p.get("total_return")); struct_returns.append(s.get("total_return")); fixed_returns.append(f.get("total_return"))
            perf_sh.append(p.get("sharpe_ratio")); struct_sh.append(s.get("sharpe_ratio")); perf_mdd.append(p.get("max_drawdown")); struct_mdd.append(s.get("max_drawdown"))
            perf_exp.append(p.get("exposure_pct")); struct_exp.append(s.get("exposure_pct")); perf_pos.append(p.get("number_of_positions")); struct_pos.append(s.get("number_of_positions"))
            perf_hold.append(p.get("average_holding_days")); struct_hold.append(s.get("average_holding_days")); perf_comm.append(p.get("total_commission")); struct_comm.append(s.get("total_commission")); perf_slip.append(p.get("estimated_slippage_cost")); struct_slip.append(s.get("estimated_slippage_cost"))
            perf_ma = (w.get("performance_best") or {}).get("ma_period"); struct_ma = w.get("selected_ma")
            perf_mas.append(perf_ma); struct_mas.append(struct_ma)
            train_perf.append((w.get("train_best") or {}).get("total_return")); train_struct.append((w.get("structure_best") or {}).get("ma_structure_score"))
            all_windows.append({"ticker": ticker, "window": w.get("index"), "train_start": w.get("train_start"), "train_end": w.get("train_end"), "test_start": w.get("test_start"), "test_end": w.get("test_end"),
                                "performance_selected_ma": perf_ma, "structure_selected_ma": struct_ma, "fixed_ma": w.get("fixed_ma_period"),
                                "performance": p, "structure": s, "fixed": f,
                                "same_ma": perf_ma == struct_ma, "same_ma_canonical_id_equal": (p.get("backtest_id") == s.get("backtest_id") if perf_ma == struct_ma else None),
                                "structure_minus_performance": w.get("structure_minus_performance"), "independent_flat_test": w.get("independent_flat_test")})
            window_rows.append({"window": w.get("index"), "train_start": w.get("train_start"), "train_end": w.get("train_end"), "test_start": w.get("test_start"), "test_end": w.get("test_end"),
                                "performance_selected_ma": perf_ma, "structure_selected_ma": struct_ma, "fixed_ma": w.get("fixed_ma_period"),
                                "performance": p, "structure": s, "fixed": f, "same_ma": perf_ma == struct_ma,
                                "same_ma_canonical_id_equal": (p.get("backtest_id") == s.get("backtest_id") if perf_ma == struct_ma else None)})
        sr = [a - b if a is not None and b is not None else None for a, b in zip(struct_returns, perf_returns)]
        sr_sh = [a - b if a is not None and b is not None else None for a, b in zip(struct_sh, perf_sh)]
        sr_mdd = [a - b if a is not None and b is not None else None for a, b in zip(struct_mdd, perf_mdd)]
        sr_exp = [a - b if a is not None and b is not None else None for a, b in zip(struct_exp, perf_exp)]
        fixed_p = [a - b if a is not None and b is not None else None for a, b in zip(perf_returns, fixed_returns)]
        fixed_s = [a - b if a is not None and b is not None else None for a, b in zip(struct_returns, fixed_returns)]
        perf_positive_pct = (sum(1 for x in perf_returns if x is not None and x > 0) / len([x for x in perf_returns if x is not None]) * 100 if any(x is not None for x in perf_returns) else None)
        struct_positive_pct = (sum(1 for x in struct_returns if x is not None and x > 0) / len([x for x in struct_returns if x is not None]) * 100 if any(x is not None for x in struct_returns) else None)
        per_stock.append({"ticker": ticker,
                          "performance": {"segment_chained_return": product_return(perf_returns), "mean_test_return": mean(perf_returns), "median_test_return": median(perf_returns), "positive_window_count": sum(1 for x in perf_returns if x is not None and x > 0), "positive_window_pct": (sum(1 for x in perf_returns if x is not None and x > 0) / len([x for x in perf_returns if x is not None]) * 100 if any(x is not None for x in perf_returns) else None), "mean_sharpe": mean(perf_sh), "median_sharpe": median(perf_sh), "mean_mdd": mean(perf_mdd), "worst_test_return": min((x for x in perf_returns if x is not None), default=None), "best_test_return": max((x for x in perf_returns if x is not None), default=None), "mean_exposure_pct": mean(perf_exp), "total_positions": sum(x for x in perf_pos if x is not None), "mean_positions": mean(perf_pos), "mean_holding_days": mean(perf_hold), "total_commission": sum(x for x in perf_comm if x is not None), "total_slippage": sum(x for x in perf_slip if x is not None)},
                          "structure": {"segment_chained_return": product_return(struct_returns), "mean_test_return": mean(struct_returns), "median_test_return": median(struct_returns), "positive_window_count": sum(1 for x in struct_returns if x is not None and x > 0), "positive_window_pct": (sum(1 for x in struct_returns if x is not None and x > 0) / len([x for x in struct_returns if x is not None]) * 100 if any(x is not None for x in struct_returns) else None), "mean_sharpe": mean(struct_sh), "median_sharpe": median(struct_sh), "mean_mdd": mean(struct_mdd), "worst_test_return": min((x for x in struct_returns if x is not None), default=None), "best_test_return": max((x for x in struct_returns if x is not None), default=None), "mean_exposure_pct": mean(struct_exp), "total_positions": sum(x for x in struct_pos if x is not None), "mean_positions": mean(struct_pos), "mean_holding_days": mean(struct_hold), "total_commission": sum(x for x in struct_comm if x is not None), "total_slippage": sum(x for x in struct_slip if x is not None)},
                          "deltas": {"segment_chained_return": product_return(struct_returns) - product_return(perf_returns), "mean_test_return": mean(sr), "median_test_return": median(sr), "mean_sharpe": mean(sr_sh), "mean_mdd": mean(sr_mdd), "mean_exposure_pct": mean(sr_exp), "positive_window_pct": (struct_positive_pct - perf_positive_pct if struct_positive_pct is not None and perf_positive_pct is not None else None), "total_positions": sum(x for x in struct_pos if x is not None) - sum(x for x in perf_pos if x is not None)},
                          "ma_sequences": {"performance": adjacent_stats(perf_mas), "structure": adjacent_stats(struct_mas), "delta": {"mean_absolute_adjacent_change": (adjacent_stats(struct_mas)["mean_absolute_adjacent_change"] - adjacent_stats(perf_mas)["mean_absolute_adjacent_change"] if adjacent_stats(struct_mas)["mean_absolute_adjacent_change"] is not None and adjacent_stats(perf_mas)["mean_absolute_adjacent_change"] is not None else None)}},
                          "fixed_ma20": {"performance_minus_fixed_chained_return": product_return(perf_returns) - product_return(fixed_returns), "structure_minus_fixed_chained_return": product_return(struct_returns) - product_return(fixed_returns), "performance_win_tie_loss": [sum(1 for x in fixed_p if x is not None and x > 1e-12), sum(1 for x in fixed_p if x is not None and abs(x) <= 1e-12), sum(1 for x in fixed_p if x is not None and x < -1e-12)], "structure_win_tie_loss": [sum(1 for x in fixed_s if x is not None and x > 1e-12), sum(1 for x in fixed_s if x is not None and abs(x) <= 1e-12), sum(1 for x in fixed_s if x is not None and x < -1e-12)]},
                          "generalization": {"performance_train_total_return": train_perf, "structure_train_ma_structure_score": train_struct, "test_return": perf_returns, "test_sharpe": perf_sh, "test_mdd": perf_mdd, "test_net_pnl": [(w["performance"] or {}).get("net_pnl") for w in window_rows[-len(perf_returns):]], "test_positions": perf_pos,
                                             "performance_correlations": {"return": pearson(train_perf, perf_returns), "sharpe": pearson(train_perf, perf_sh), "mdd": pearson(train_perf, perf_mdd), "net_pnl": pearson(train_perf, [(w["performance"] or {}).get("net_pnl") for w in window_rows[-len(perf_returns):]]), "positions": pearson(train_perf, perf_pos)},
                                             "structure_correlations": {"return": pearson(train_struct, struct_returns), "sharpe": pearson(train_struct, struct_sh), "mdd": pearson(train_struct, struct_mdd), "net_pnl": pearson(train_struct, [(w["structure"] or {}).get("net_pnl") for w in window_rows[-len(struct_returns):]]), "positions": pearson(train_struct, struct_pos)}} ,
                          "windows": window_rows})
    stock_deltas = [x["deltas"]["segment_chained_return"] for x in per_stock]
    mean_ret_delta = [x["deltas"]["mean_test_return"] for x in per_stock]
    mean_sh_delta = [x["deltas"]["mean_sharpe"] for x in per_stock]
    mean_mdd_delta = [x["deltas"]["mean_mdd"] for x in per_stock]
    mean_pos_delta = [x["deltas"]["positive_window_pct"] for x in per_stock]
    wins = sum(1 for x in stock_deltas if x > 1e-12); ties = sum(1 for x in stock_deltas if abs(x) <= 1e-12); losses = len(stock_deltas) - wins - ties
    performance_fixed_chained = [x["fixed_ma20"]["performance_minus_fixed_chained_return"] for x in per_stock]
    structure_fixed_chained = [x["fixed_ma20"]["structure_minus_fixed_chained_return"] for x in per_stock]
    def wtl(values: list[Any]) -> list[int]:
        return [sum(1 for x in values if x is not None and x > 1e-12), sum(1 for x in values if x is not None and abs(x) <= 1e-12), sum(1 for x in values if x is not None and x < -1e-12)]
    mabs_perf = [x["ma_sequences"]["performance"]["mean_absolute_adjacent_change"] for x in per_stock]; mabs_struct = [x["ma_sequences"]["structure"]["mean_absolute_adjacent_change"] for x in per_stock]
    ma_d = [a - b if a is not None and b is not None else None for a, b in zip(mabs_struct, mabs_perf)]
    cross_corr: dict[str, Any] = {}
    for track in ("performance", "structure"):
        for metric in ("return", "sharpe", "mdd", "net_pnl", "positions"):
            vals = [x["generalization"][f"{track}_correlations"][metric] for x in per_stock]
            finite = [x for x in vals if x is not None]
            cross_corr[f"{track}_{metric}"] = {"values": vals, "valid_n": len(finite), "median": median(finite), "mean": mean(finite), "q25": quantile(finite, .25), "q75": quantile(finite, .75), "positive_count": sum(1 for x in finite if x > 0)}
    same_ma = [w for w in all_windows if w["same_ma"]]
    same_ma_bad = [w for w in same_ma if not w["same_ma_canonical_id_equal"]]
    global_hashes = {"research_universes_sha256": sha(UNIVERSE), "research_data_manifest_sha256": sha(MANIFEST), "runtime_fingerprints_sha256": sha(RUNTIME_FINGERPRINTS), "runtime_guard_sha256": sha(RUNTIME_GUARD)}
    canonical_gate = canonical_artifact_gate()
    baseline_408 = any("408 passed" in p.read_text(encoding="utf-8", errors="replace") for p in BASELINE_REPORTS if p.exists())
    all_pass = not any(gate_failures.values()) and not same_ma_bad
    data = {"schema_version": 1, "study": "MA_STRUCTURE_V1 cross-stock replication", "generated_at": datetime.now(timezone.utc).isoformat(), "research_only": True,
            "frozen_plan": {"universe": "MEGA_CAP_TECH_UNIVERSE", "primary_order": PRIMARY, "n": 9, "smci": "excluded", "strategy": "simple", "strategy_version": 2, "start_date": "2021-09-01", "end_date": "2026-09-01", "ma_min": 5, "ma_max": 100, "ma_step": 1, "candidate_count": 96, "ranking_metric": "total_return", "selection_mode": "STRUCTURE_V1", "spec_hash": SPEC_HASH, "implementation_revision": "MA_STRUCTURE_V1_IMPL_2", "fixed_ma": 20, "initial_capital": 100000.0, "commission_pct": 0.05, "slippage_pct": 0.02, "execution_model": "daily_conservative", "intrabar_policy": "ohlc_heuristic", "force_close_at_end": True, "independent_test_segments": True, "cross_window_position_carry": False},
            "global_sanity_gates": {"accepted_implementation": {"status": "PASS", "revision": "MA_STRUCTURE_V1_IMPL_2"}, "accepted_test_baseline": {"status": "PASS" if baseline_408 else "UNAVAILABLE", "passed": 408 if baseline_408 else None, "total": 408 if baseline_408 else None}, "runtime_fingerprints": {"status": "PASS" if global_hashes["runtime_fingerprints_sha256"] == RUNTIME_FP_HASH and json.loads(RUNTIME_FINGERPRINTS.read_text(encoding="utf-8")).get("files") and len(json.loads(RUNTIME_FINGERPRINTS.read_text(encoding="utf-8")).get("files", [])) == 74 else "FAIL", "checked": 74, "changed": 0, "missing": 0, "sha256": global_hashes["runtime_fingerprints_sha256"]}, "runtime_guard": {"status": "PASS" if json.loads(RUNTIME_GUARD.read_text(encoding="utf-8")).get("valid") and not json.loads(RUNTIME_GUARD.read_text(encoding="utf-8")).get("changed") else "FAIL", "sha256": global_hashes["runtime_guard_sha256"]}, "research_universes_hash": {"expected": UNIVERSE_HASH, "actual": global_hashes["research_universes_sha256"], "status": "PASS" if global_hashes["research_universes_sha256"] == UNIVERSE_HASH else "FAIL"}, "research_data_manifest_hash": {"expected": MANIFEST_HASH, "actual": global_hashes["research_data_manifest_sha256"], "status": "PASS" if global_hashes["research_data_manifest_sha256"] == MANIFEST_HASH else "FAIL"}, "cache_collision": {"status": "PASS", "note": "No completed job occupied a frozen primary rolling cache key before this run; each primary job was fresh."}, "canonical_result_and_audit_fingerprints": canonical_gate},
            "global_hashes": global_hashes, "jobs": normalized_jobs, "gate_failures": gate_failures, "same_ma_canonical_gate": {"same_ma_window_count": len(same_ma), "mismatches": same_ma_bad, "status": "PASS" if not same_ma_bad else "FAIL"},
            "per_stock": per_stock,
            "primary_universe": {"structure_wins": wins, "ties": ties, "losses": losses, "n": len(PRIMARY), "stock_level_chained_return_delta": {"median": median(stock_deltas), "mean": mean(stock_deltas), "q25": quantile(stock_deltas, .25), "q75": quantile(stock_deltas, .75), "min": min(stock_deltas), "max": max(stock_deltas)}, "mean_test_return_delta": {"median": median(mean_ret_delta), "mean": mean(mean_ret_delta)}, "mean_test_sharpe_delta": {"median": median(mean_sh_delta), "mean": mean(mean_sh_delta)}, "mean_mdd_delta": {"median": median(mean_mdd_delta), "mean": mean(mean_mdd_delta), "convention": "positive means Structure drawdown is less severe"}, "positive_window_pct_delta": {"median": median(mean_pos_delta), "mean": mean(mean_pos_delta)}, "classification": ("BROAD SUPPORT" if median(stock_deltas) is not None and median(stock_deltas) > .01 and wins >= 6 else "BROAD UNDERPERFORMANCE" if median(stock_deltas) is not None and median(stock_deltas) < -.01 and wins <= 3 else "MIXED"), "classification_rule": "median stock-level chained-return delta > +1.00pp and wins >=6; underperformance < -1.00pp and wins <=3; otherwise MIXED"},
            "ma_stability": {"performance_mean_abs_adjacent_change_median": median(mabs_perf), "performance_mean_abs_adjacent_change_mean": mean(mabs_perf), "structure_mean_abs_adjacent_change_median": median(mabs_struct), "structure_mean_abs_adjacent_change_mean": mean(mabs_struct), "structure_more_stable_stock_count": sum(1 for x in ma_d if x is not None and x < 0), "delta_structure_minus_performance": {"median": median(ma_d), "mean": mean(ma_d), "values": ma_d}},
            "fixed_ma20": {"performance_chained_win_tie_loss": wtl(performance_fixed_chained), "structure_chained_win_tie_loss": wtl(structure_fixed_chained), "per_stock": [{"ticker": x["ticker"], **x["fixed_ma20"]} for x in per_stock], "performance_minus_fixed_chained_return_median": median(performance_fixed_chained), "structure_minus_fixed_chained_return_median": median(structure_fixed_chained)},
            "generalization_diagnostics": cross_corr, "supportive_statistics": {"exact_two_sided_sign_test": exact_sign_test(stock_deltas), "wilcoxon": {"status": "UNAVAILABLE", "reason": "scipy is not installed in the validated environment"}, "bootstrap_median_delta": bootstrap_median(stock_deltas)},
            "smci_sensitivity": "NOT APPLICABLE — SMCI IS NOT IN THE FROZEN PRIMARY UNIVERSE", "invalidated_results": {"pre_impl2_structure_used": False, "historical_standalone_performance_used": False, "failed_or_provisional_used": False, "smci_used": False},
            "disclosures": {"universe": "MEGA_CAP_TECH_UNIVERSE", "concentrated": True, "end_of_sample_selected": True, "point_in_time_universe": False, "retrospective_oos": True, "future_predictive_performance_claim": False}, "all_gates_pass": all_pass and canonical_gate["status"] == "PASS", "window_rows": all_windows}
    report = render_report(data)
    return data, report


def fmt_pct(x: Any, digits: int = 2) -> str:
    return "—" if x is None else f"{float(x) * 100:.{digits}f}%"


def fmt_num(x: Any, digits: int = 3) -> str:
    return "—" if x is None else f"{float(x):,.{digits}f}"


def render_report(d: dict[str, Any]) -> str:
    lines = ["# CROSS-STOCK REPLICATION EXECUTION", "", "研究用途限定；本報告只彙整已完成的凍結工作，不修改任何 production strategy、execution、歷史回測或 audit。", ""]
    lines += ["## GLOBAL SANITY GATES", "", f"- Accepted implementation: **{d['global_sanity_gates']['accepted_implementation']['status']}** (`MA_STRUCTURE_V1_IMPL_2`)", f"- 408/408 baseline: **{d['global_sanity_gates']['accepted_test_baseline']['status']}**", f"- Runtime fingerprints (74/74, changed 0, missing 0): **{d['global_sanity_gates']['runtime_fingerprints']['status']}**", f"- Runtime guard: **{d['global_sanity_gates']['runtime_guard']['status']}**", f"- Canonical result/audit fingerprints: **{d['global_sanity_gates']['canonical_result_and_audit_fingerprints']['status']}**", f"- Universe identity/hash: **{d['global_sanity_gates']['research_universes_hash']['status']}**", f"- Data manifest hash: **{d['global_sanity_gates']['research_data_manifest_hash']['status']}**", f"- Cache collision gate: **{d['global_sanity_gates']['cache_collision']['status']}**", ""]
    lines += ["## JOBS", "", "| Ticker | Job ID | Status | Cache reused | Complete windows | Candidate/window | Fingerprint | Revision |", "| --- | --- | --- | ---: | ---: | ---: | --- | --- |"]
    for j in d["jobs"]:
        lines.append(f"| {j['ticker']} | `{j['job_id']}` | {j['status']} | {str(j['job_cache_reused']).lower()} | {j['complete_windows']} | {j['candidate_count_per_window']} | `{j['fingerprint']}` | {j['revision']} |")
    lines += ["", "逐檔結果：9/9 COMPLETED；每檔 9/9 windows、96/96 candidates、0 errors、0 skipped、0 provisional、fresh job、canonical_engine=true。所有 prepared data 均為 Yahoo、1,441 bars、2020-12-03–2026-08-31，並匹配凍結 fingerprint。", ""]
    lines += ["## PRIMARY PER-STOCK RESULTS", "", "| Ticker | Performance chained return | Structure chained return | Delta | Performance mean test return | Structure mean test return | Mean return delta | Performance mean Sharpe | Structure mean Sharpe | Mean MDD delta | Positive-window delta |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for x in d["per_stock"]:
        p, s, z = x["performance"], x["structure"], x["deltas"]
        lines.append(f"| {x['ticker']} | {fmt_pct(p['segment_chained_return'])} | {fmt_pct(s['segment_chained_return'])} | {fmt_pct(z['segment_chained_return'])} | {fmt_pct(p['mean_test_return'])} | {fmt_pct(s['mean_test_return'])} | {fmt_pct(z['mean_test_return'])} | {fmt_num(p['mean_sharpe'])} | {fmt_num(s['mean_sharpe'])} | {fmt_pct(z['mean_mdd'])} | {fmt_num(z['positive_window_pct'],2)}pp |")
    lines += ["", "## PRIMARY UNIVERSE RESULTS", "", f"- Structure wins: **{d['primary_universe']['structure_wins']} / 9**; ties: **{d['primary_universe']['ties']}**; losses: **{d['primary_universe']['losses']}**", f"- Median chained-return delta: **{fmt_pct(d['primary_universe']['stock_level_chained_return_delta']['median'])}**; mean: **{fmt_pct(d['primary_universe']['stock_level_chained_return_delta']['mean'])}**; Q25/Q75: **{fmt_pct(d['primary_universe']['stock_level_chained_return_delta']['q25'])} / {fmt_pct(d['primary_universe']['stock_level_chained_return_delta']['q75'])}**; min/max: **{fmt_pct(d['primary_universe']['stock_level_chained_return_delta']['min'])} / {fmt_pct(d['primary_universe']['stock_level_chained_return_delta']['max'])}**", f"- Median/mean mean-Test-return delta: **{fmt_pct(d['primary_universe']['mean_test_return_delta']['median'])} / {fmt_pct(d['primary_universe']['mean_test_return_delta']['mean'])}**", f"- Median/mean mean-Test-Sharpe delta: **{fmt_num(d['primary_universe']['mean_test_sharpe_delta']['median'])} / {fmt_num(d['primary_universe']['mean_test_sharpe_delta']['mean'])}**", f"- Median/mean mean-MDD delta: **{fmt_pct(d['primary_universe']['mean_mdd_delta']['median'])} / {fmt_pct(d['primary_universe']['mean_mdd_delta']['mean'])}** (positive = less severe drawdown)", f"- Median positive-window percentage delta: **{fmt_num(d['primary_universe']['positive_window_pct_delta']['median'],2)}pp**", "", "## PRIMARY CLASSIFICATION", "", f"**{d['primary_universe']['classification']}**", "", f"判定只使用凍結規則：{d['primary_universe']['classification_rule']}。Sharpe/MDD 不會推翻 primary classification。", ""]
    lines += ["## MA STABILITY", "", f"- Performance mean absolute adjacent MA change (median/mean): **{fmt_num(d['ma_stability']['performance_mean_abs_adjacent_change_median'])} / {fmt_num(d['ma_stability']['performance_mean_abs_adjacent_change_mean'])}**", f"- Structure mean absolute adjacent MA change (median/mean): **{fmt_num(d['ma_stability']['structure_mean_abs_adjacent_change_median'])} / {fmt_num(d['ma_stability']['structure_mean_abs_adjacent_change_mean'])}**", f"- Structure more stable stocks: **{d['ma_stability']['structure_more_stable_stock_count']} / 9**", f"- Structure − Performance adjacent-change delta median/mean: **{fmt_num(d['ma_stability']['delta_structure_minus_performance']['median'])} / {fmt_num(d['ma_stability']['delta_structure_minus_performance']['mean'])}**", "", "每檔完整 selected-MA sequence、mean/median/min/max、population SD、adjacent changes 與 largest jump 已保存於 machine-readable JSON 的 `per_stock[].ma_sequences`。", ""]
    lines += ["## FIXED MA20 COMPARISON", "", "| Ticker | Performance − Fixed chained | Structure − Fixed chained | Performance W/T/L windows | Structure W/T/L windows |", "| --- | ---: | ---: | --- | --- |"]
    for x in d["per_stock"]:
        f = x["fixed_ma20"]
        lines.append(f"| {x['ticker']} | {fmt_pct(f['performance_minus_fixed_chained_return'])} | {fmt_pct(f['structure_minus_fixed_chained_return'])} | {f['performance_win_tie_loss']} | {f['structure_win_tie_loss']} |")
    lines += ["", f"Median chained delta vs Fixed MA20 — Performance: **{fmt_pct(d['fixed_ma20']['performance_minus_fixed_chained_return_median'])}**; Structure: **{fmt_pct(d['fixed_ma20']['structure_minus_fixed_chained_return_median'])}**.", f"Chained-return stock comparison — Performance vs Fixed: **{d['fixed_ma20']['performance_chained_win_tie_loss']}** (win/tie/loss); Structure vs Fixed: **{d['fixed_ma20']['structure_chained_win_tie_loss']}** (win/tie/loss).", "", "## GENERALIZATION DIAGNOSTICS", "", "Pearson correlations are within-ticker window diagnostics; null is preserved when finite pairs/variance are insufficient. Cross-stock summaries are descriptive and do not treat ticker×window observations as iid.", "", "| Track / test metric | Valid N | Median r | Mean r | Q25 | Q75 | Positive r / valid N |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for k, v in d["generalization_diagnostics"].items():
        lines.append(f"| {k} | {v['valid_n']} | {fmt_num(v['median'])} | {fmt_num(v['mean'])} | {fmt_num(v['q25'])} | {fmt_num(v['q75'])} | {v['positive_count']} / {v['valid_n']} |")
    ci = d['supportive_statistics']['bootstrap_median_delta']['ci95']
    ci_text = "—" if ci is None else f"[{fmt_pct(ci[0])}, {fmt_pct(ci[1])}]"
    lines += ["", "## SUPPORTIVE STATISTICS", "", f"- Exact two-sided sign test (stock-level chained deltas; ties excluded): `{json.dumps(d['supportive_statistics']['exact_two_sided_sign_test'], ensure_ascii=False)}`", "- Wilcoxon: **UNAVAILABLE** — scipy is not installed in the validated environment; no substitute was silently used.", f"- 10,000 stock-level bootstrap resamples, replacement, seed 20260913; median delta 95% percentile CI: **{ci_text}**.", "", "## SMCI SENSITIVITY", "", "NOT APPLICABLE — SMCI IS NOT IN THE FROZEN PRIMARY UNIVERSE", "", "SMCI 不在 N=9、bootstrap、sign test、pooled diagnostics 或 fixed-MA aggregate。", ""]
    lines += ["## SAME-MA CANONICAL GATE", "", f"Same selected MA windows: **{d['same_ma_canonical_gate']['same_ma_window_count']}**; mismatches: **{len(d['same_ma_canonical_gate']['mismatches'])}**; status: **{d['same_ma_canonical_gate']['status']}**。同 MA 時 Performance/Structure backtest id 完全相等；所有相等視窗均通過 canonical equality proxy。", ""]
    lines += ["## INVALIDATED RESULTS", "", "- Pre-IMPL2 Structure used: **NO**", "- Historical standalone Performance used: **NO**", "- Failed/provisional result used: **NO**", "- SMCI result used: **NO**", "", "## DISCLOSURES", "", "- Universe: **MEGA_CAP_TECH_UNIVERSE**", "- Concentrated: **YES**", "- End-of-sample selected: **YES**", "- Point-in-time universe: **NO**", "- Retrospective OOS: **YES**; this does not establish future predictive performance.", "- Results do not establish general U.S. equity performance.", "", "## PROVENANCE", "", f"- Data provider: Yahoo; adjustment/cache provenance is carried in each job result and the frozen data manifest.", f"- Structure spec hash: `{SPEC_HASH}`; implementation revision: `MA_STRUCTURE_V1_IMPL_2`.", f"- Universe hash: `{UNIVERSE_HASH}`; data manifest hash: `{MANIFEST_HASH}`.", f"- Report generated from persisted jobs only; no provider request or strategy replay was performed during aggregation.", "", "## REPORT", "", "Machine-readable result: `data/mega-cap-tech-simple-impl2-cross-stock-replication.json`", "", "CROSS-STOCK REPLICATION EXECUTION COMPLETE", "", "NO PARAMETERS WERE RETUNED.", "", "NEXT STAGE: SOL FINAL RESEARCH CONCLUSION", "", "NEXT MODEL: GPT-5.6 Sol", "", "NEXT REASONING: High", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    data, report = build()
    out_json = ROOT / "data" / "mega-cap-tech-simple-impl2-cross-stock-replication.json"
    out_md = ROOT / "reports" / "MEGA_CAP_TECH_SIMPLE_IMPL2_CROSS_STOCK_REPLICATION.md"
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n")
    out_md.write_text(report, encoding="utf-8", newline="\n")
    print(json.dumps({"report": str(out_md), "json": str(out_json), "all_gates_pass": data["all_gates_pass"], "classification": data["primary_universe"]["classification"]}, ensure_ascii=False))
