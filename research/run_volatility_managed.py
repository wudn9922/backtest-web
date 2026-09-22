from __future__ import annotations

import json
import sys

from research.volatility_managed_study import publish, run

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result, robustness, walk_forward = run(lambda message: print(message, flush=True))
    publish(result, robustness, walk_forward)
    print(json.dumps({
        "evidence_grade": result["evidence_grade"], "next_family": result["next_family"],
        "primary_spy": result["primary_spy"], "robustness": result["robustness_summary"],
        "walk_forward": result["walk_forward_summary"], "runtime_seconds": result["runtime_seconds"],
    }, ensure_ascii=False), flush=True)
