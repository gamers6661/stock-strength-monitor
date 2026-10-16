"""Same-generation service, pools, details and export acceptance."""
import csv,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,emotion_relay as E,relay_pools as W,ui_payload
OUT=Path(__file__).parent
def get(path):return json.load(urllib.request.urlopen('http://127.0.0.1:8848'+path,timeout=30))
status=get('/__status');assert status['phase']=='ready',status['phase']
assert status['code_emotion_relay_hash']==status['snapshot_emotion_relay_hash']==E.IMPLEMENTATION_HASH
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'));E.validate(s)
assert s['emotion_relay']['version']==E.VERSION
by={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
caps=s['emotion_relay']['lists']['sealed'];verified=[];missing=[]
for c in caps:
    m=by[c]['emotion_relay'];strength=m['cap_strength']
    assert m['valid'] and m['sealed'] and m['price']==m['limit_price']
    if m['height_exact']:assert m['height']==(m['prior_height'] or 0)+1
    assert '当前涨停' in m['events'] and not any('待收盘' in e for e in m['events'])
    assert '一字价格区间·成交受限' not in m['risks']
    if strength['verified']:
        assert strength['height_rank'] is not None or not m['height_exact']
        verified.append(c)
    else:missing.append(dict(code=c,reason=strength['reason']))
assert verified
version=status['ui_generation'];summary=ui_payload.unpack(get('/__ui/summary?version='+version))
assert summary['ui_generation']==version and summary['emotion_relay']['lists']['sealed']==caps
codes=verified[:2]
for c in codes:
    detail=get('/__ui/detail?version='+version+'&kind=stock&id='+c)
    assert detail['version']==version
    assert detail['item']['emotion_relay']['cap_strength']==by[c]['emotion_relay']['cap_strength']
request=urllib.request.Request('http://127.0.0.1:8848/__ui/export',data=json.dumps(dict(version=version,codes=codes,contexts=dict(view='emotion'))).encode(),headers={'Content-Type':'application/json'})
text=urllib.request.urlopen(request,timeout=30).read().decode('utf-8-sig');export=list(csv.DictReader(text.splitlines()))
assert len(export)==len(codes)
for row,c in zip(export,codes):
    m=by[c]['emotion_relay'];assert row['当前板位']==str(m['height']) and '当前涨停' in row['事件']
    assert json.loads(row['封板强度依据'])['verified'] is True
    assert abs(float(row['封单金额(亿元)'])-m['cap_strength']['seal_amount_yuan']/1e8)<1e-6
    assert row['UI版本']==version
(OUT/'涨停池核对.csv').write_text(text,encoding='utf-8-sig')
result=dict(pid=status['pid'],generation=version,version=E.VERSION,capture=s['quote_capture_at'],
            pool_source_at=s['emotion_relay']['pools']['source_at'],sealed=len(caps),strength_valid=len(verified),missing=missing,
            one_price=sum('一字板' in by[c]['emotion_relay']['risks'] for c in caps),
            promotion=[dict(height=p['height'],sealed=p['sealed']) for p in s['emotion_relay']['promotion']],
            source_to_publish=status.get('last_pipeline_performance'),checks=['backend','summary','details','CSV'])
(OUT/'release_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
