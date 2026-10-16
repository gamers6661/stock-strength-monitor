"""Inspect the actual daily limit pool and raw-price history before rule design."""
import json,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config,datafeed as D
OUT=Path(__file__).resolve().parent
items=[('limits_'+d,'https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=10000&sort=fbt:asc&date='+d) for d in ('20261014','20261013','20261012')]
items += [('raw_000995',host+'?param=sz000995,day,,,65,') for host in config.KLINE['hosts'][:2]]
def get(item):
    key,url=item;start=time.monotonic()
    try:return dict(key=key,url=url,seconds=round(time.monotonic()-start,3),value=json.loads(D.http_get(url,timeout=8,retry=0)))
    except Exception as e:return dict(key=key,url=url,error=type(e).__name__+': '+str(e))
with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(get,items))
(OUT/'provider_probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
for x in results:
    v=x.get('value') or {};data=v.get('data') or {};p=data.get('pool') or []
    print({k:v for k,v in x.items() if k!='value'},'keys',list(v),'data_keys',list(data),'pool_count',len(p),'sample',str(p[:1] or data.get('sz000995',{}))[:800],flush=True)
