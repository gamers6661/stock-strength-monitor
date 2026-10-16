import json,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import datafeed as D
OUT=Path(__file__).resolve().parent
jobs={
 'sohu':'https://q.stock.sohu.com/hisHq?code=cn_600825,cn_002343,cn_601811,cn_605577&start=20260801&end=20261015&stat=1&order=A&period=d',
 'halts':'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_CUSTOM_SUSPEND_DATA&columns=ALL&pageSize=500&pageNumber=1&sortColumns=SUSPEND_START_DATE&sortTypes=-1',
 'em_raw':'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600825&klt=101&fqt=0&beg=20260801&end=20261015&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
 'cninfo':'https://www.cninfo.com.cn/new/hisAnnouncement/query?column=sse&tabName=fulltext&pageSize=30&pageNum=1&stock=600825&seDate=2026-09-01~2026-10-15',
 'halt_pdf':'https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-10-13/600825_20261013_DQIX.pdf',
}
def work(kv):
 key,url=kv;t=time.monotonic()
 try:
  if key=='halt_pdf':
   import urllib.request
   with urllib.request.urlopen(url,timeout=12) as response:payload=response.read()
   (OUT/'新华传媒_停牌核查_20261013.pdf').write_bytes(payload)
   return dict(key=key,url=url,bytes=len(payload),seconds=round(time.monotonic()-t,2))
  text=D.http_get(url,timeout=12,retry=0);(OUT/(key+'.txt')).write_text(text,encoding='utf-8')
  return dict(key=key,url=url,bytes=len(text),head=text[:350],seconds=round(time.monotonic()-t,2))
 except Exception as e:return dict(key=key,url=url,error=repr(e),seconds=round(time.monotonic()-t,2))
with ThreadPoolExecutor(max_workers=5) as executor:result=list(executor.map(work,jobs.items()))
(OUT/'probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)
