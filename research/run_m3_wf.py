"""Offline runner; acknowledged stdout chunks, never production persistence."""
import hashlib,json,sys
from research.m3_wf_study import run

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    body,folds=run(lambda s:print(s,flush=True))
    serial={k:json.dumps(v,ensure_ascii=True,allow_nan=False,default=str,separators=(',',':')) for k,v in {'report':body,'folds':folds}.items()}
    print('M3_WF_READY '+json.dumps({k:{'chars':len(v),'chunks':(len(v)+149999)//150000,'sha256':hashlib.sha256(v.encode()).hexdigest()} for k,v in serial.items()}),flush=True)
    while True:
        req=input().strip()
        if req=='done':break
        name,index=req.split();i=int(index);chunk=serial[name][i*150000:(i+1)*150000]
        print(f'STREAM_BEGIN {name} {i}')
        print('\n'.join(chunk[j:j+60] for j in range(0,len(chunk),60)))
        print(f'STREAM_END {name} {i}',flush=True)
