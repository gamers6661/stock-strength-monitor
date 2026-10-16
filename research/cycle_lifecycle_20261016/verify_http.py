import csv,io,json,sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T,ui_payload
OUT=Path(__file__).parent;BASE='http://127.0.0.1:8848'
def get(path):
    with urlopen(BASE+path,timeout=25) as r:return r.read()
status=json.loads(get('/__status'));assert status['phase']=='ready' and status['last_scan_ok']
assert status['code_ma_trend_hash']==status['snapshot_ma_trend_hash']==T.IMPLEMENTATION_HASH
html=get('/dashboard.html').decode('utf8');packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip())
brief=ui_payload.unpack(packet);generation=brief['ui_generation'];assert generation==status['ui_generation']
rows={r['code']:r for r in brief['stocks']+brief.get('coverage_catalog',[])}
codes=['002552','000995','605058','603386']
for stage in (5,10,20):
    matches=[c for c,r in rows.items() if r['ma_trend'].get('stage')==stage and r['ma_trend'].get('status')!='已退出']
    codes+=matches[:1]
    codes+=[c for c in matches if rows[c]['ma_trend'].get('progressing')][:1]
codes=list(dict.fromkeys(codes));details={}
for code in codes:
    response=json.loads(get('/__ui/detail?'+urlencode(dict(version=generation,kind='stock',id=code))))
    row=response['item'];m=row['ma_trend'];details[code]=row;assert response['version']==generation
    assert T.brief(m)==rows[code]['ma_trend'] and m['version']==T.VERSION
    if m.get('cycle_id'):
        assert m['origin']['date']==m['cycle_id']
        assert not any(t['from_stage'] in (10,20) and t['to_stage']==5 for t in m['transitions'])
    if m.get('progressing') and m['status']!='已退出' and not m['pending']:
        assert m['stage'] in (10,20) and not m['eligible'] and m.get('advance')
for view in ('radar','ranking'):
    body=json.dumps(dict(version=generation,codes=codes,contexts=dict(view=view))).encode('utf8')
    with urlopen(Request(BASE+'/__ui/export',body,headers={'Content-Type':'application/json'},method='POST'),timeout=30) as response:payload=response.read()
    (OUT/(view+'_acceptance.csv')).write_bytes(payload)
    for exported in csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))):
        m=details[exported['代码']]['ma_trend'];assert exported['UI版本']==generation
        assert json.loads(exported['完整均线依据'])==m
        if m['status']=='已退出':assert not exported['起点日期' if view=='radar' else '本轮启动日']
        else:
            assert exported['起点日期' if view=='radar' else '本轮启动日']==str((m.get('origin') or {}).get('date') or '')
            assert exported['阶段确认日']==str(m.get('entry_date') or ((m.get('origin') or {}).get('confirmation') or {}).get('date') or '')
            assert exported['再启动确认日']==str(((m.get('restart_event') or {}).get('confirmation') or {}).get('date') or '')
result=dict(at=datetime.now().isoformat(),pid=status['pid'],generation=generation,version=T.VERSION,hash=T.IMPLEMENTATION_HASH,
    source=brief['quote_capture_at'],completed=brief['strength_model']['asof'],published=status['last_publish_at'],
    counts=brief['ma_trend']['counts'],details_csv_same_generation=True,
    samples=[dict(code=c,name=rows[c]['name'],**{k:details[c]['ma_trend'].get(k) for k in ('stage','status','eligible','progressing','origin','restart_event','entry_date','last_exit','quote_at')}) for c in codes])
(OUT/'http_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'live_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False))
