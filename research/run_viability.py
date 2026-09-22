"""Run and optionally persist the three requested research artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from research import ROOT
from research.viability_report import render
from research.viability_study import run


def _write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-simple-v2-viability")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write only the three declared data artifacts and Markdown report")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    progress = (lambda value: print(value, file=sys.stderr, flush=True)) if args.progress else (lambda _value: None)
    report, entries, folds = run(progress)
    serialized = {
        ROOT / "data/simple-v2-entry-zone-forward-returns.json": json.dumps(entries, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        ROOT / "data/simple-v2-walk-forward-folds.json": json.dumps(folds, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        ROOT / "data/simple-v2-strategy-viability.json": json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
    }
    markdown = render(report)
    if args.write:
        for path, text in serialized.items():
            _write_atomic(path, text)
        _write_atomic(ROOT / "reports/simple-v2-strategy-viability.md", markdown)
        print(json.dumps({"written": [str(p.relative_to(ROOT)) for p in serialized] + ["reports/simple-v2-strategy-viability.md"],
                          "decision": report["decision"], "runtime_seconds": report["runtime_seconds"]}, ensure_ascii=False))
    else:
        print(json.dumps({"report": report, "entry_zone": entries, "walk_forward": folds}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

