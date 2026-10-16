import gzip,json,sqlite3,sys
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed as D,ma_trend as T,ui_payload
OUT=Path(__file__).parent
with urlopen('http://127.0.0.1:8848/__status',timeout=10) as response:status=json.load(response)
with urlopen('http://127.0.0.1:8848/__ui/summary?version='+status['ui_generation'],timeout=15) as response:s=ui_payload.unpack(json.load(response))
rows=s['stocks']+s.get('coverage_catalog',[]);candidates=[r for r in rows if r['ma_trend'].get('recovery_current')]
cohort=[]
with sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro',uri=True) as con:
    for row in candidates:
        m=row['ma_trend'];event=m['recovery_candidate'];bars=[b for b in D.load_kline(con,'kline','code',row['code'],limit=160) if b['date']<=m['asof']]
        event_index=next(i for i,b in enumerate(bars) if b['date']==event['date'])
        observations=[];first_pass=None
        for i in range(event_index+1,min(len(bars),event_index+T.P['limit_recovery_candidate_days'])):
            b=bars[i];line5=T.average(bars,i,5);line10=T.average(bars,i,10)
            alive=all(bars[j]['close']>=T.average(bars,j,10) for j in range(event_index+1,i+1))
            passed=(alive and b['close']>bars[i-1]['close'] and b['close']>event['price'] and b['close']>=line5
                and line5>T.average(bars,i-1,5) and line10>T.average(bars,i-1,10))
            observations.append(dict(date=b['date'],close=b['close'],ma5=line5,ma10=line10,pass_follow=passed))
            if passed and first_pass is None:first_pass=b['date']
        cohort.append(dict(code=row['code'],name=row['name'],event=event['date'],age=event['age_sessions'],
            quote_at=m['quote_at'],price=m['price'],first_follow_confirmation=first_pass,observations=observations))
(OUT/'candidate_audit.json').write_text(json.dumps(dict(generation=status['ui_generation'],source=s['quote_capture_at'],
    candidates=len(cohort),follow_confirmed=sum(bool(r['first_follow_confirmation']) for r in cohort),rows=cohort),ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(candidates=len(cohort),follow_confirmed=sum(bool(r['first_follow_confirmation']) for r in cohort),rows=cohort),ensure_ascii=False))
