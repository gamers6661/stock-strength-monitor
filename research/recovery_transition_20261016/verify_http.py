import csv,io,json,math,sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T,ui_payload,config,intraday
OUT=Path(__file__).parent;BASE='http://127.0.0.1:8848'
def get(path):
    with urlopen(BASE+path,timeout=25) as r:return r.read()
status=json.loads(get('/__status'))
assert status['phase']=='ready' and status['last_scan_ok']
assert status['code_ma_trend_hash']==status['snapshot_ma_trend_hash']==T.IMPLEMENTATION_HASH
html=get('/dashboard.html').decode('utf8');packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip())
brief=ui_payload.unpack(packet);generation=brief['ui_generation'];assert generation==status['ui_generation']
rows={r['code']:r for r in brief['stocks']+brief.get('coverage_catalog',[])}
expected={'000995':('2026-10-13','2026-10-15'),'605058':('2026-10-12','2026-10-13'),'603386':('2026-10-13','2026-10-15'),'002639':('2026-10-13','2026-10-14')}
codes=list(expected)+['603216','603067','000710','002956'];details={}
for code in codes:
    response=json.loads(get('/__ui/detail?'+urlencode(dict(version=generation,kind='stock',id=code))))
    m=response['item']['ma_trend'];details[code]=response['item'];assert response['version']==generation
    assert T.brief(m)==rows[code]['ma_trend']
    assert m['version']==T.VERSION
    if code in expected:
        assert m['stage']==5 and not m.get('candidate_mode') and not m.get('recovery_current')
        assert (m['origin']['date'],m['origin']['confirmation']['date'])==expected[code]
        assert m['quote_at'][:10]==status['last_scan'][:10]
        assert datetime.fromisoformat(m['valid_until'].replace('Z','+00:00')).replace(tzinfo=None)>=datetime.now()
        chart=response['item']['chart_history']
        assert chart[-1]['date']==m['quote_at'][:10] and chart[-1]['close']==m['price']
        assert chart[-2]['date']==m['asof']
    if code=='605058':assert m['origin']['confirmation']['prior_ma20_touched'] is False
for view in ('radar','ranking'):
    body=json.dumps(dict(version=generation,codes=codes,contexts=dict(view=view))).encode('utf8')
    with urlopen(Request(BASE+'/__ui/export',body,headers={'Content-Type':'application/json'},method='POST'),timeout=30) as response:payload=response.read()
    (OUT/(view+'_acceptance.csv')).write_bytes(payload)
    for exported in csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))):
        code=exported['代码'];m=details[code]['ma_trend'];assert exported['UI版本']==generation
        assert json.loads(exported['完整均线依据'])==m
        if code in expected:
            assert exported['阶段确认日']==expected[code][1]
            assert exported['起点日期' if view=='radar' else '本轮启动日']==expected[code][0]
            assert not exported['涨停收复候选日期']
        if code=='002956':assert not exported['起点日期' if view=='radar' else '本轮启动日']
result=dict(checked_at=str(datetime.now()),pid=status['pid'],generation=generation,source=brief['quote_capture_at'],
    version=T.VERSION,hash=T.IMPLEMENTATION_HASH,counts=brief['ma_trend']['counts'],same_generation_detail_csv=True,
    samples=[dict(code=c,name=rows[c]['name'],**{k:details[c]['ma_trend'].get(k) for k in ('stage','status','eligible','origin','quote_at','valid_until')}) for c in codes])
(OUT/'http_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False))
