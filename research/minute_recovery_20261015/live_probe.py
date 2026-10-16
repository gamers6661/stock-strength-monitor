import json,sys
from pathlib import Path
from collections import Counter
from urllib.request import urlopen
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT.parents[1]));import ui_payload
s=json.loads(urlopen('http://127.0.0.1:8848/__status',timeout=15).read())
print({k:s.get(k) for k in ('phase','last_scan_ok','last_publish_ok','snapshot_quote_capture_at','ui_generation','scan_active','scan_progress')},flush=True)
if s.get('phase')!='ready':sys.exit(0)
data=ui_payload.unpack(json.loads(urlopen('http://127.0.0.1:8848/__ui/summary?version='+s['ui_generation'],timeout=20).read()))
rows=data['stocks']+data.get('coverage_catalog',[]);models=[r.get('ma_trend') or {} for r in rows]
report=dict(status=s,meta=data['ma_trend'],statuses=dict(Counter(m['status'] for m in models)),
    pending=[dict(code=r['code'],name=r['name'],model=r['ma_trend']) for r in rows if r['ma_trend']['status']=='支撑过程待核验'],
    no_trade=[dict(code=r['code'],name=r['name'],coverage=r['ma_trend']['minute_coverage']) for r in rows if (r['ma_trend'].get('minute_coverage') or {}).get('no_trade_minutes')],
    candidates=[dict(code=r['code'],name=r['name'],event=r['ma_trend']['recovery_candidate']) for r in rows if (r['ma_trend'].get('recovery_candidate') or {}).get('active')])
(OUT/'live_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('source',data['ma_trend']['source_at'],'fetch',data['ma_trend']['minute_fetch'],'statuses',report['statuses'],'no_trade',len(report['no_trade']),'candidates',len(report['candidates']),flush=True)
print('pending',[(r['code'],r['name'],r['model']['reason']) for r in report['pending']],flush=True)
