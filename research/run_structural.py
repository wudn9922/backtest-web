"""Offline structural validation; stdout only, no mutation of saved backtests."""
import hashlib
import json
import sys
import time

from research import ROOT
from research.baseline import load, immutable_fingerprints
from research.run_ablation import canonical_checks
from research.structural_data import load_inputs
from research.structural_study import run_study


def previous_checks(body):
    saved=json.loads((ROOT/"data/first-tp-family-decomposition.json").read_text(encoding="utf-8"))
    aliases={"A":"ADVANCED_FULL","B":"FIRST_TP_SIGNAL_ONLY_NO_PARTIAL",
             "C":"FIRST_TP_SIGNAL_PLUS_PROTECTIVE_NO_PARTIAL","E":"EXTREME_TP_OFF"}
    checks=[]
    for key,name in aliases.items():
        old=next(r for r in saved["portfolio"] if r["name"]==name)
        new=next(r for r in body["portfolio"] if (r["symbol"],r["period"],r["policy"],r["candidate"])==("NVDA","FULL","conservative",key))
        assert old["summary"]==new["summary"]
        assert old["exposure"]==new["exposure"]
        assert old["equity_sha256"]==new["equity_sha256"]
        assert old["execution_sha256"]==new["execution_sha256"]
        checks.append({"candidate":key,"previous_name":name,"policy":"conservative","metrics_equal":True,
                       "exposure_equal":True,"equity_equal":True,"executions_equal":True})
    policies=json.loads((ROOT/"data/intrabar-ambiguity-attribution.json").read_text(encoding="utf-8"))
    for old in policies["portfolio"]:
        if old["name"]!="ADVANCED_FULL":
            continue
        new=next(r for r in body["portfolio"] if (r["symbol"],r["period"],r["policy"],r["candidate"])==("NVDA","FULL",old["policy"],"A"))
        assert all(old[k]==new[k] for k in ("summary","exposure","equity_sha256","execution_sha256"))
        checks.append({"candidate":"A","previous_name":"ADVANCED_FULL_AMBIGUITY_STUDY","policy":old["policy"],
                       "metrics_equal":True,"exposure_equal":True,"equity_equal":True,"executions_equal":True})
    return checks


def run(progress=False):
    started=time.perf_counter()
    before=immutable_fingerprints()
    frozen,daily=load()
    manifest,frames=load_inputs()
    checks=canonical_checks(frozen,daily)
    body=run_study(frozen,frames,progress=(lambda s:print(s,file=sys.stderr,flush=True)) if progress else lambda s:None)
    prior=previous_checks(body)
    after=immutable_fingerprints()
    assert before==after
    # Re-read every data hash: no provider call or data refresh is allowed in run.
    load_inputs()
    return {"schema_version":1,"study":"First TP structural candidate validation","research_only":True,
        "optimization_performed":False,"production_strategy_version":2,
        "canonical":{k:{"backtest_id":v["id"],"request":v["request"],"result_sha256":v["result_sha256"],
                        "summary":v["result"]["summary"],"data_coverage":v["result"]["data_coverage"],
                        "reproducibility":v["result"]["reproducibility"]} for k,v in frozen.items()},
        "data_manifest":manifest,"canonical_validation":checks,"previous_research_verification":prior,
        "immutability":{"before":before,"after":after,"unchanged":True},
        "research_source_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"research").glob("*.py")},
        "runtime_seconds":time.perf_counter()-started,**body}


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    data=run(progress="--progress" in sys.argv)
    if "--stream" in sys.argv:
        # Acknowledged stdout chunks avoid terminal output truncation. The
        # calling editor applies the final artifact; this script never writes.
        serialized=json.dumps(data,ensure_ascii=True,allow_nan=False,default=str,separators=(",",":"))
        chunks=[serialized[i:i+150000] for i in range(0,len(serialized),150000)]
        print(f"STREAM_READY {len(chunks)} {hashlib.sha256(serialized.encode()).hexdigest()}",flush=True)
        while True:
            requested=input()
            if requested=="done":
                break
            i=int(requested)
            chunk=chunks[i]
            print(f"STREAM_BEGIN {i}")
            print("\n".join(chunk[j:j+60] for j in range(0,len(chunk),60)))
            print(f"STREAM_END {i}",flush=True)
        raise SystemExit(0)
    args=[a for a in sys.argv[1:] if a!="--progress"]
    if args:
        if args[0]=="sizes":
            data={k:len(json.dumps(v,default=str)) for k,v in data.items()}
        else:
            for key in args[0].split("/"):
                data=data[slice(*(int(n) for n in key.split(":")))] if isinstance(data,list) and ":" in key else data[int(key)] if isinstance(data,list) else data[key]
    print(json.dumps(data,ensure_ascii=False,allow_nan=False,default=str,separators=(",",":")))
