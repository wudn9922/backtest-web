"""Run offline and print JSON to stdout; never write research or production data."""
import json
import math
import time
import sys
from research.baseline import load, immutable_fingerprints, digest, normalize_timestamps, CACHE, EXPECTED_ADVANCED_SOURCE_SHA256
from research.simulation import Prepared
from research.analysis import build_analysis
from app.backtest.engine import BacktestEngine


def canonical_checks(frozen, daily):
    checks={}
    for name, saved in frozen.items():
        expected=normalize_timestamps(saved["result"])
        actual=normalize_timestamps(BacktestEngine().run(saved["request_object"],daily))
        assert expected["executions"]==actual["executions"]
        assert expected["equity_curve"]==actual["equity_curve"]
        assert expected["summary"]==actual["summary"]
        for a,b in zip(expected["positions"],actual["positions"]):
            assert {k:v for k,v in a.items() if k!="gross_pnl"}=={k:v for k,v in b.items() if k!="gross_pnl"}
            assert math.isclose(a["gross_pnl"],b["gross_pnl"],abs_tol=1e-9)
        checks[name]={"executions_differences":0,"positions_differences_excluding_gross_fp_rounding":0,
                      "net_pnl_differences":0,"equity_differences":0,"metrics_differences":0,
                      "gross_reporting_max_abs_fp_difference":max(abs(a["gross_pnl"]-b["gross_pnl"]) for a,b in zip(expected["positions"],actual["positions"])),
                      "timestamp_comparison":"same instant normalized to UTC; saved strings unchanged"}
    return checks


def run():
    begin=time.perf_counter();before=immutable_fingerprints();frozen,daily=load()
    checks=canonical_checks(frozen,daily)
    prepared=Prepared(frozen["advanced"]["request_object"],daily)
    result={"schema_version":1,"study":"Advanced v2 fixed-parameter module ablation",
            "research_only":True,"optimization_performed":False,
            "research_harness":{"production_advanced_source_sha256":EXPECTED_ADVANCED_SOURCE_SHA256,
                "modules_entry_point":"research.modules.VARIANTS",
                "baseline_checks":"production replay; all-on parity; 77 anchored full lifecycles; immutable DB/cache/source",
                "dependency_definitions_file":"research/README.md"},
            "canonical":{name:{"backtest_id":s["id"],"strategy_version":2,"policy":"conservative",
                "request":s["request"],"reproducibility":s["result"]["reproducibility"],
                "data_coverage":s["result"]["data_coverage"],"metrics":s["result"]["summary"],
                "result_sha256":s["result_sha256"]} for name,s in frozen.items()},
            "shared_data":{"path":str(CACHE),"bars_including_warmup":len(daily),"bars_in_study":len(prepared.period),
                           "sha256":before["parquet"],"same_ohlcv_across_canonicals":True},
            "canonical_replay_validation":checks}
    result.update(build_analysis(prepared,frozen))
    after=immutable_fingerprints();assert after==before
    result["immutability"]={"before":before,"after":after,"unchanged":True}
    result["runtime_seconds"]=time.perf_counter()-begin
    return result


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(),ensure_ascii=False,allow_nan=False,separators=(",",":")))
