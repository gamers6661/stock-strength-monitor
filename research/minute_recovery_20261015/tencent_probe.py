import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import datafeed as D
OUT=Path(__file__).resolve().parent
out=[]
for code in ('sh603701','sh603235'):
    url='https://web.ifzq.gtimg.cn/appstock/app/kline/mkline?param='+code+',m1,,320'
    try:
        raw=D.http_get(url,timeout=7,retry=0);value=json.loads(raw)
        out.append(dict(symbol=code,url=url,value=value));data=(value.get('data') or {}).get(code) or {}
        print(code,'keys',list(data),'sample',str(data)[:300],'gaps',[b for b in data.get('m1',[]) if str(b[0])[8:12] in ('1005','1011','1020')],flush=True)
    except Exception as e:out.append(dict(symbol=code,url=url,error=str(e)));print(code,type(e).__name__,str(e),flush=True)
(OUT/'tencent_probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
