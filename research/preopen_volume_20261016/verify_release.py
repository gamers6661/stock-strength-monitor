import csv,json,sys,time,urllib.request,difflib
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,market_strength as M,ma_trend as T,emotion_relay as E,ui_payload
OUT=Path(__file__).parent
def get(path):return json.load(urllib.request.urlopen('http://127.0.0.1:8848'+path,timeout=20))
deadline=time.monotonic()+420
while time.monotonic()<deadline:
    status=get('/__status')
    if status['phase']=='error':raise RuntimeError(status.get('last_scan_error'))
    if status['phase']=='ready' and status.get('last_publish_ok'):break
    time.sleep(5)
else:raise TimeoutError('Publication not ready')
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
(OUT/'published_snapshot.json').write_text(json.dumps(s,ensure_ascii=False),encoding='utf-8')
for name,mod in [('market_strength',M),('ma_trend',T),('emotion_relay',E)]:
    assert status['code_'+name+'_hash']==status['snapshot_'+name+'_hash']==mod.IMPLEMENTATION_HASH
M.validate(s);T.validate(s);E.validate(s)
version=status['ui_generation'];summary=ui_payload.unpack(get('/__ui/summary?version='+version))
assert summary['ui_generation']==version and summary['ma_trend']==s['ma_trend']
rows=s['stocks']+s.get('coverage_catalog',[]);by={r['code']:r for r in rows}
assert not any(n['leader']=='600825' for n in by['000530']['emotion_relay']['continuation'])
assert not any(n['leader']=='002696' for n in by['000530']['emotion_relay'].get('companions',[]))
assert any(n['leader']=='600825' and n['board']=='传媒' for n in by['002343']['emotion_relay']['continuation'])
assumed=s.get('data_availability') or {}
assert any(v['kind']=='inferred_suspension' for v in assumed.values())
assert not any('历史窗口不连续' in m['reason'] or '最新完成交易日历史未覆盖' in m['reason'] for r in rows if (m:=r['ma_trend']))
cases={}
for c in ['000530','002343','600825','001246','601091']:
    d=get('/__ui/detail?version='+version+'&kind=stock&id='+c);assert d['version']==version
    item=d['item'];bars=item.get('chart_history') or item.get('strength_history') or []
    assert bars,(c,'candles missing')
    if c=='600825':assert bars[-1]['date']=='2026-10-12' and item['emotion_relay']['height']==10
    cases[c]=dict(name=item['name'],candles=len(bars),last=bars[-1]['date'],gaps=item.get('chart_observation'),status=item['ma_trend']['status'])
req=urllib.request.Request('http://127.0.0.1:8848/__ui/export',data=json.dumps(dict(version=version,codes=['000530','002343'],contexts=dict(view='emotion'))).encode(),headers={'Content-Type':'application/json'})
csv_text=urllib.request.urlopen(req,timeout=25).read().decode('utf-8-sig');parsed=list(csv.DictReader(csv_text.splitlines()))
assert len(parsed)==2 and '成交量(万股)' in parsed[0] and '成交额(亿元)' in parsed[0] and '封单金额(亿元)' in parsed[0]
for row in parsed:
    m=by[row['代码']]['emotion_relay']
    assert abs(float(row['成交量(万股)'])-m['volume_yi']*1e4)<1e-5
assert version in csv_text and E.IMPLEMENTATION_HASH in csv_text
(OUT/'情绪核对.csv').write_text('\ufeff'+csv_text,encoding='utf-8')
report=dict(generation=version,pid=status['pid'],session=s['session'],reference=s.get('reference_view'),capture=s['quote_capture_at'],
    ma=s['ma_trend']['counts'],pending=Counter(r['ma_trend']['reason'] for r in rows if r['ma_trend']['pending']),ms=s['market_strength']['coverage'],
    availability=Counter(v['kind'] for v in assumed.values()),cases=cases,csv_rows=len(parsed))
(OUT/'live_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
diff=[]
for p in (OUT/'baseline').iterdir():
    current=ROOT/p.name
    if current.is_file() and current.read_bytes()!=p.read_bytes():diff.extend(difflib.unified_diff(p.read_text(encoding='utf-8').splitlines(True),current.read_text(encoding='utf-8').splitlines(True),fromfile='baseline/'+p.name,tofile=p.name))
for name in ['completed_reference.py','test_preopen_reference.py']:
    diff.extend(difflib.unified_diff([], (ROOT/name).read_text(encoding='utf-8').splitlines(True),fromfile='/dev/null',tofile=name))
(OUT/'source_changes.diff').write_text(''.join(diff),encoding='utf-8')
