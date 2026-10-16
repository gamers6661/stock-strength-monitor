import json,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import datafeed as D
OUT=Path(__file__).resolve().parent
def probe(item):
    code,url=item;start=time.monotonic()
    try:
        raw=D.http_get(url,timeout=7,retry=0)
        return dict(code=code,url=url,seconds=round(time.monotonic()-start,3),raw=raw)
    except Exception as e:return dict(code=code,url=url,error=str(e))
items=[]
for code in ('603701','603235'):
    symbol='sh'+code
    items.extend((code,url) for url in (
        'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol='+symbol+'&scale=1&ma=no&datalen=1023',
        'https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData?symbol='+symbol+'&scale=1&ma=no&datalen=1023',
        'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code='+symbol,
    ))
with ThreadPoolExecutor(max_workers=3) as p:out=list(p.map(probe,items))
(OUT/'gap_probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
for x in out:
    raw=x.get('raw','');is_json=raw.startswith('[')
    try:
        if is_json:bars=json.loads(raw)
        elif 'getKLineData' in x['url']:bars=json.loads(raw[raw.find('([')+1:raw.rfind(');')])
        else:bars=[]
    except Exception:bars=[]
    print({k:v for k,v in x.items() if k!='raw'},'length',len(raw),'gap_bars',[b for b in bars if str(b.get('day','')).startswith('2026-10-15') and str(b['day'])[11:16] in ('10:05','10:11','10:20')],flush=True)
