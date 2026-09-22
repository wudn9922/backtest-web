"""Offline output to stdout only; artifacts are applied separately."""
import json
import sys
import time
from research.baseline import load, immutable_fingerprints
from research.run_ablation import canonical_checks
from research.simulation import Prepared


def run(phase):
    started = time.perf_counter()
    before = immutable_fingerprints()
    frozen, daily = load()
    checks = canonical_checks(frozen, daily)
    prepared = Prepared(frozen["advanced"]["request_object"], daily)
    if phase == "A":
        from research.policy_study import analyze
        body = analyze(prepared, frozen)
    elif phase == "B":
        from research.family_study import analyze
        body = analyze(prepared, frozen["advanced"]["result"]["positions"])
    else:
        raise ValueError("phase must be A or B")
    after = immutable_fingerprints()
    assert before == after
    return {"schema_version": 1, "phase": phase, "research_only": True, "parameter_optimization": False,
        "canonical": {k: {"backtest_id": v["id"], "request": v["request"], "result_sha256": v["result_sha256"],
            "data_coverage": v["result"]["data_coverage"], "reproducibility": v["result"]["reproducibility"],
            "metrics": v["result"]["summary"]} for k, v in frozen.items()},
        "canonical_validation": checks, "immutability": {"before": before, "after": after, "unchanged": True},
        "runtime_seconds": time.perf_counter()-started, **body}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result = run(sys.argv[1])
    if len(sys.argv) > 2:
        if sys.argv[2] == "sizes":
            result = {k:len(json.dumps(v,default=str)) for k,v in result.items()}
        elif sys.argv[2] == "header":
            result = {k:v for k,v in result.items() if k in ["schema_version","phase","research_only","parameter_optimization","canonical","canonical_validation","immutability","runtime_seconds"]}
        else:
            for key in sys.argv[2].split("/"):
                if isinstance(result, list):
                    result = result[slice(*(int(n) for n in key.split(":")))] if ":" in key else result[int(key)]
                else:
                    result = result[key]
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, default=str, separators=(",", ":")))
