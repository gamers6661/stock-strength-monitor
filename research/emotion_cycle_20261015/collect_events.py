import json,sys,urllib.parse,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import relay_data as D,datafeed
OUT=Path(__file__).resolve().parent;cal=json.loads((OUT/'calendar.json').read_text(encoding='utf-8'));days=cal[-31:]+['2026-10-15'];records={};errors=[]
for day in days:
 path=D.root()/'halts'/(day+'.json');saved=D.read(path)
 if saved:records[day]=saved;continue
 params=dict(reportName='RPT_CUSTOM_SUSPEND_DATA_INTERFACE',columns='ALL',pageSize=500,pageNumber=1,sortColumns='SUSPEND_START_DATE',sortTypes=-1,source='WEB',client='WEB',filter='(MARKET="全部")(DATETIME=\''+day+'\')')
 try:
  value=json.loads(datafeed.em_get('https://datacenter-web.eastmoney.com/api/data/v1/get?'+urllib.parse.urlencode(params),timeout=8));result=value.get('result') or {}
  if not value.get('success') or not isinstance(result.get('data'),list) or len(result['data'])!=result.get('count'):raise ValueError('停牌表完整性未通过')
  record=dict(day=day,source='eastmoney_exchange_suspension_table',rows=result['data'],fetched_at=str(D.datetime.now()));records[day]=record;D.write(path,record)
 except Exception as e:errors.append(dict(day=day,error=repr(e)))
 print('halts',day,'records',len((records.get(day) or {}).get('rows',[])),'errors',len(errors),flush=True)
(OUT/'halts_history.json').write_text(json.dumps(dict(days=records,errors=errors),ensure_ascii=False),encoding='utf-8')
latest=records.get(days[-1],{});print('types',sorted({r['SUSPEND_EXPIRE'] for r in latest.get('rows',[])}),flush=True)
