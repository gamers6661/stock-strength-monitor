import csv,io,json,math,sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T,ui_payload,intraday,config
OUT=Path(__file__).parent;BASE='http://127.0.0.1:8848'
def get(path):
    with urlopen(BASE+path,timeout=20) as r:return r.read()
status=json.loads(get('/__status'))
assert status['phase']=='ready' and status['last_scan_ok']
assert status['code_ma_trend_hash']==status['snapshot_ma_trend_hash']==T.IMPLEMENTATION_HASH
html=get('/dashboard.html').decode('utf8')
packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip())
brief=ui_payload.unpack(packet);version=brief['ui_generation']
assert version==status['ui_generation']
assert brief['ma_trend']['implementation_hash']==T.IMPLEMENTATION_HASH
rows=brief['stocks']+brief.get('coverage_catalog',[])
current=next(r for r in rows if r['ma_trend'].get('stage')==20 and r['ma_trend']['eligible'])
past=next(r for r in rows if r['ma_trend']['status']=='已退出' and (r['ma_trend'].get('origin') or {}).get('date','').startswith('2026-06'))
selected=[current,past];details={}
for row in selected:
    response=json.loads(get('/__ui/detail?'+urlencode(dict(version=version,kind='stock',id=row['code']))))
    assert response['version']==version
    details[row['code']]=response['item']
    assert response['item']['ma_trend']['version']==T.VERSION
    assert T.brief(response['item']['ma_trend'])==row['ma_trend']
for view in ('radar','ranking'):
    body=json.dumps(dict(version=version,codes=[r['code'] for r in selected],contexts=dict(view=view))).encode('utf8')
    with urlopen(Request(BASE+'/__ui/export',body,headers={'Content-Type':'application/json'},method='POST'),timeout=30) as response:payload=response.read()
    (OUT/(view+'_acceptance.csv')).write_bytes(payload)
    exported=list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))
    for row in exported:
        assert row['UI版本']==version
        assert json.loads(row['完整均线依据'])==details[row['代码']]['ma_trend']
    assert exported[0]['均线阶段']=='MA20横盘再启动'
    assert exported[1]['均线阶段']=='暂无当前阶段'
    assert not exported[1]['起点日期' if view=='radar' else '本轮启动日']
    if view=='radar':
        model=details[current['code']]['ma_trend']
        assert math.isclose(float(exported[0]['MA20第一道触线价']),model['primary_support_price'])
        assert (exported[0]['第二道固定平台底部']=='')==(model['secondary_support_price'] is None)
now=datetime.now();at=intraday.parse_quote_timestamp(current['ma_trend']['quote_at'])
age=(now-at).total_seconds()
assert 0<=age<=config.INTRADAY['max_quote_age_seconds']
result=dict(checked_at=str(now),pid=status['pid'],generation=version,version=T.VERSION,
    implementation_hash=T.IMPLEMENTATION_HASH,quote_at=str(at),quote_age_seconds=round(age,1),
    publish_source_age_seconds=(status.get('last_pipeline_performance') or {}).get('latest_quote_age_seconds_at_publish'),
    counts=brief['ma_trend']['counts'],current_code=current['code'],current_name=current['name'],
    archived_code=past['code'],archived_origin=past['ma_trend']['origin']['date'],
    same_generation_detail_csv=True,chart_latest_date=(details[current['code']].get('chart_history') or [{}])[-1].get('date'))
(OUT/'http_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False))
