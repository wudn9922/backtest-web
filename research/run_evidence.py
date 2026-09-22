"""Run offline; emit acknowledged stdout blocks for the editor to save."""
import hashlib
import json
import sys
from research.evidence_study import run

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    body,table=run(lambda s:print(s,flush=True))
    serialized={k:json.dumps(v,ensure_ascii=True,allow_nan=False,separators=(',',':'),default=str)
                for k,v in {'report':body,'table':table}.items()}
    print('EVIDENCE_READY '+json.dumps({k:{'chars':len(s),'chunks':(len(s)+149999)//150000,
        'sha256':hashlib.sha256(s.encode()).hexdigest()} for k,s in serialized.items()}),flush=True)
    while True:
        req=input().strip()
        if req=='done':break
        name,index=req.split(); i=int(index); chunk=serialized[name][i*150000:(i+1)*150000]
        print(f'STREAM_BEGIN {name} {i}')
        print('\n'.join(chunk[j:j+60] for j in range(0,len(chunk),60)))
        print(f'STREAM_END {name} {i}',flush=True)
