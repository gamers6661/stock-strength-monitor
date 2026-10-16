import csv,json,sys,urllib.request,difflib
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,market_strength as M,ma_trend as T,emotion_relay as E,ui_payload
OUT=Path(__file__).parent
def get(path):return json.load(urllib.request.urlopen('http://127.0.0.1:8848'+path,timeout=20))
status=get('/__status');s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
assert status['phase']=='ready' and status['last_publish_ok'] and status['last_scan_ok'],status['phase']
for name,mod in [('market_strength',M),('ma_trend',T),('emotion_relay',E)]:
    assert status['code_'+name+'_hash']==status['snapshot_'+name+'_hash']==mod.IMPLEMENTATION_HASH
M.validate(s);T.validate(s);E.validate(s)
version=status['ui_generation'];summary=ui_payload.unpack(get('/__ui/summary?version='+version))
assert summary['ui_generation']==version
assert summary['ma_trend']==s['ma_trend'] and summary['emotion_relay']==s['emotion_relay']
rows=s['stocks']+s.get('coverage_catalog',[]);by={r['code']:r for r in rows}
assert not any(n['leader']=='600825' for n in by['000530']['emotion_relay']['continuation'])
assert not any(n['leader']=='002696' for n in by['000530']['emotion_relay'].get('companions',[]))
assert any(n['leader']=='600825' and n['board']=='传媒' for n in by['002343']['emotion_relay']['continuation'])
assert not any('历史窗口不连续' in m['reason'] or '最新完成交易日历史未覆盖' in m['reason'] for r in rows if (m:=r['ma_trend']))
assumptions=s.get('data_availability') or {}
inferred=[c for c,v in assumptions.items() if v.get('kind')=='inferred_suspension']
assert inferred and all(assumptions[c]['attempts']==1 and assumptions[c]['peer_success_count']>0 for c in inferred)
cases=['000530','002343','600825','001246','601091']
gapped=next((r['code'] for r in rows if (r['ma_trend'].get('history_observation') or {}).get('suspension_days') and not r['ma_trend']['pending'] and r['code'] not in inferred),None)
if gapped:cases.append(gapped)
details={}
for c in cases:
    detail=get('/__ui/detail?version='+version+'&kind=stock&id='+c)
    assert detail['version']==version
    item=detail['item'];bars=item.get('chart_history') or item.get('strength_history') or []
    if c in ('600825','001246','601091'):
        assert bars,(c,'missing actual candles')
    if c=='600825':assert bars[-1]['date']=='2026-10-12' and item['emotion_relay']['height']==10
    details[c]=dict(name=item['name'],candles=len(bars),last=bars[-1]['date'] if bars else None,
        gaps=item.get('chart_observation'),availability=item.get('data_availability'),status=item['ma_trend']['status'])
req=urllib.request.Request('http://127.0.0.1:8848/__ui/export',data=json.dumps(dict(version=version,codes=['000530','002343'],contexts=dict(view='emotion'))).encode(),headers={'Content-Type':'application/json'})
csv_text=urllib.request.urlopen(req,timeout=25).read().decode('utf-8-sig')
parsed=list(csv.reader(csv_text.splitlines()));assert len(parsed)==3 and len(parsed[0])==len(parsed[1])==len(parsed[2])
assert all(k in parsed[0] for k in ('成交额(亿元)','成交量(亿股)','封单金额(亿元)'))
assert version in csv_text and E.IMPLEMENTATION_HASH in csv_text
(OUT/'情绪核对.csv').write_text('\ufeff'+csv_text,encoding='utf-8')
report=dict(version=version,pid=status['pid'],capture=s['quote_capture_at'],quote_at=s['market_strength']['close_verification']['source_at'],
    ma=s['ma_trend']['counts'],pending=Counter(r['ma_trend']['reason'] for r in rows if r['ma_trend']['pending']),
    availability=Counter(v['kind'] for v in assumptions.values()),ms=s['market_strength']['coverage'],cases=details,
    csv_rows=len(parsed)-1,hashes={name:mod.IMPLEMENTATION_HASH for name,mod in [('market_strength',M),('ma_trend',T),('emotion_relay',E)]})
(OUT/'live_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
diff=[]
for path in sorted((OUT/'baseline').iterdir()):
    current=ROOT/path.name
    if current.is_file() and current.read_bytes()!=path.read_bytes():
        diff.extend(difflib.unified_diff(path.read_text(encoding='utf-8').splitlines(True),current.read_text(encoding='utf-8').splitlines(True),fromfile='baseline/'+path.name,tofile=path.name))
(OUT/'source_changes.diff').write_text(''.join(diff),encoding='utf-8')
with (OUT/'source_changes.diff').open('a',encoding='utf-8') as f:
    for name in ('observed_history.py','relay_relations.py','test_observed_history.py'):
        f.writelines(difflib.unified_diff([], (ROOT/name).read_text(encoding='utf-8').splitlines(True),fromfile='/dev/null',tofile=name))
