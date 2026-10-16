import json,sys,time,urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import relay_data as D,datafeed
OUT=Path(__file__).resolve().parent;universe=json.loads((OUT/'universe.json').read_text(encoding='utf-8'));cal=json.loads((OUT/'calendar.json').read_text(encoding='utf-8'));asof=cal[-1];begin=cal[-66]
def fetch(codes):
 url='https://q.stock.sohu.com/hisHq?'+urllib.parse.urlencode(dict(code=','.join('cn_'+c for c in codes),start=begin.replace('-',''),end=asof.replace('-',''),stat=1,order='A',period='d'))
 payload=json.loads(datafeed.http_get(url,timeout=10,retry=0));result={}
 if not isinstance(payload,list):raise ValueError('参考日线返回格式异常')
 for value in payload:
  code=str(value.get('code','')).removeprefix('cn_')
  if value.get('status')!=0 or code not in codes or code in result:raise ValueError('参考日线代码/状态异常')
  bars=[]
  for r in value.get('hq',[]):
   bar=dict(date=r[0],open=float(r[1]),close=float(r[2]),reference_close=float(Decimal(r[2])-Decimal(r[3])),change_pct=float(r[4].removesuffix('%')),low=float(r[5]),high=float(r[6]),volume=float(r[7])*100,turnover_pct=float(r[9].removesuffix('%')) if r[9]!='-' else None)
   if not D.intraday._valid_historical_price_bar(bar) or bar['reference_close']<=0:raise ValueError('参考原价/前收无效')
   bars.append(bar)
  result[code]=dict(code=code,bars=bars,source='sohu_hisHq_raw',coverage_through=asof,requested_from=begin)
 return result
codes=list(universe);batches=[codes[i:i+50] for i in range(0,len(codes),50)];records={};errors=[];start=time.monotonic()
with ThreadPoolExecutor(max_workers=6) as executor:
 jobs={executor.submit(fetch,chunk):chunk for chunk in batches}
 for job in as_completed(jobs):
  try:
   values=job.result();records.update(values)
   for c,r in values.items():D.write(D.root()/'reference'/(c+'.json'),r)
   absent=set(jobs[job])-set(values)
   if absent:errors.append(dict(codes=sorted(absent),reason='返回缺少代码'))
  except Exception as e:errors.append(dict(codes=jobs[job],reason=repr(e)))
result=dict(calendar=cal,reference=records,errors=errors,seconds=round(time.monotonic()-start,2));(OUT/'reference_universe.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');print('reference',len(records),'errors',errors,'seconds',result['seconds'],flush=True)
