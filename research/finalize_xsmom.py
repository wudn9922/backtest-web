"""Refresh presentation from immutable completed results, never rerun a strategy."""
import json
from research import ROOT
from research.xsmom import verify_spec
from research.xsmom_report import render
from research.baseline import immutable_fingerprints
from research.environment_v3_data import sha256_file


def main():
    verify_spec()
    def read(name): return json.loads((ROOT/"data"/name).read_text(encoding="utf-8"))
    result=read("cross-sectional-momentum-benchmark.json")
    assert immutable_fingerprints()==result["invariance"]["after"]
    assert sha256_file(ROOT/"data/research-candidate-registry.json")==result["invariance"]["registry_sha256"]
    folds=read("cross-sectional-momentum-walk-forward.json")["folds"]
    monthly=read("cross-sectional-momentum-monthly-holdings.json")["ranking_timeline"]
    text=render(result,folds,monthly)
    (ROOT/"reports/cross-sectional-momentum-benchmark.md").write_text(text,encoding="utf-8")
    print("Report refreshed from frozen results; invariance verified")


if __name__=="__main__": main()
