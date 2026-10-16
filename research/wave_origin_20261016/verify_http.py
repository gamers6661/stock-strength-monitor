import csv,io,json,sys
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
expected={'002552':('2026-08-04','2026-08-06','2026-08-31'),'000700':('2026-06-02','2026-06-03','2026-06-11'),
          '000510':('2026-08-04','2026-08-05','2026-08-19'),'603122':('2026-09-16','2026-09-18','2026-10-12')}
codes=list(expected)+['000995','605058','603386'];details={}
for code in codes:
    response=json.loads(get('/__ui/detail?'+urlencode(dict(version=generation,kind='stock',id=code))))
    m=response['item']['ma_trend'];details[code]=response['item'];assert response['version']==generation
    assert T.brief(m)==rows[code]['ma_trend'] and m['version']==T.VERSION
    if code in expected:
        e=m['last_exit'];o=e['origin'];assert (o['date'],o['confirmation']['date'],e['date'])==expected[code]
        assert o['kind']=='涨停重建均线后确认'
    if code=='002552':assert m['origin']['date']!='2026-06-15'
for view in ('radar','ranking'):
    body=json.dumps(dict(version=generation,codes=codes,contexts=dict(view=view))).encode('utf8')
    with urlopen(Request(BASE+'/__ui/export',body,headers={'Content-Type':'application/json'},method='POST'),timeout=30) as response:payload=response.read()
    (OUT/(view+'_acceptance.csv')).write_bytes(payload)
    for exported in csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))):
        c=exported['代码'];m=details[c]['ma_trend'];assert exported['UI版本']==generation
        assert json.loads(exported['完整均线依据'])==m
        if m['status']=='已退出':
            assert not exported['起点日期' if view=='radar' else '本轮启动日']
            assert exported['均线阶段']=='暂无当前阶段'
result=dict(checked_at=__import__('datetime').datetime.now().isoformat(),pid=status['pid'],generation=generation,version=T.VERSION,hash=T.IMPLEMENTATION_HASH,
    source=brief['quote_capture_at'],completed=brief['strength_model']['asof'],counts=brief['ma_trend']['counts'],same_generation_detail_csv=True,
    samples=[dict(code=c,name=rows[c]['name'],**{k:details[c]['ma_trend'].get(k) for k in ('stage','status','eligible','origin','last_exit','quote_at')}) for c in codes])
(OUT/'http_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'live_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False))
