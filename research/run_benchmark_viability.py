from __future__ import annotations

import json
import sys

from research.benchmark_viability_report import write_report
from research.benchmark_viability_study import run, write_outputs

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result = run()
    write_outputs(result)
    write_report(result)
    print(json.dumps({"grades": result["grades"], "next_family": result["next_family"], "runtime_seconds": result["runtime_seconds"]}, ensure_ascii=False))

