"""全池同源日级资金历史，按完成日增补，不混入当日未收盘数据。"""
from concurrent.futures import ThreadPoolExecutor,as_completed,TimeoutError
from datetime import datetime
import json
import math
import time

import config
import datafeed

VERSION='日级资金历史1'
SOURCE='新浪超大单+大单日级净额'

def path():return config.CACHE_DIR/'fund_history'/'sina_main.json'

def load():
    try:record=json.loads(path().read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
    return record.get('stocks') or {} if record.get('version')==VERSION else {}

def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def refresh(codes,calendar,workers=8,deadline=180):
    if not calendar:return dict(requested=0,updated=0,failed=0)
    asof=calendar[-1];cache=load();dates=calendar[-20:]
    def due(code):
        item=cache.get(code) or {}
        if item.get('checked_asof')!=asof:return True
        if not item.get('error'):return False
        try:return (datetime.now()-datetime.fromisoformat(item['checked_at'])).total_seconds()>=1800
        except (KeyError,ValueError):return True
    todo=[c for c in codes if due(c)]
    def work(code):
        try:
            rows=datafeed.fetch_sina_fundflow(code,days=30)
            rows=[r for r in rows if r.get('date','')<=asof and number(r.get('main_net'))]
            if not rows:raise ValueError('同源资金未返回可用历史')
            if rows[-1]['date']!=asof:raise ValueError('同源资金最近完成日'+rows[-1]['date']+'，未覆盖目标日'+asof)
            return code,rows,None
        except Exception as exc:return code,[],str(exc)[:160]
    updated=failed=0;started=time.monotonic();truncated=False
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures={executor.submit(work,c):c for c in todo}
        try:
            for future in as_completed(futures,timeout=deadline):
                code,rows,error=future.result();old=cache.get(code) or {}
                item=dict(old,source=SOURCE,checked_at=datetime.now().isoformat(sep=' ',timespec='seconds'),checked_asof=asof)
                if error:
                    item['error']=error;failed+=1
                else:
                    prior=old.get('rows') or [] if old.get('source')==SOURCE else []
                    bydate={r['date']:r for r in prior+rows}
                    item.update(rows=[bydate[d] for d in sorted(bydate)],error=None)
                    updated+=1
                cache[code]=item
                if (updated+failed)%500==0:print(f'[资金历史] {updated+failed}/{len(todo)}；成功{updated}、缺口{failed}',flush=True)
        except TimeoutError:
            truncated=True
            for future in futures:future.cancel()
    path().parent.mkdir(parents=True,exist_ok=True)
    config.atomic_write_text(path(),json.dumps(dict(version=VERSION,asof=asof,stocks=cache),ensure_ascii=False,separators=(',',':')))
    complete=sum(len(dates)==20 and all(d in {r['date'] for r in (cache.get(c) or {}).get('rows',[]) if number(r.get('main_net'))} for d in dates) for c in codes)
    return dict(requested=len(todo),updated=updated,failed=failed,complete20=complete,
                total=len(codes),asof=asof,truncated=truncated,seconds=round(time.monotonic()-started,1))
