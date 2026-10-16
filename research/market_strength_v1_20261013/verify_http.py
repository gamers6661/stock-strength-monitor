"""Read-only HTTP list/detail/export verification for one immutable publication."""
import csv,io,json,hashlib
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlencode
import sys
sys.path.insert(0,str(Path.cwd()))
import config,ui_payload,market_strength as M
out=Path('research/market_strength_v1_20261013');base='http://127.0.0.1:8848'
def get(path):return urlopen(base+path,timeout=90).read()
status=json.loads(get('/__status'));assert status['phase']=='ready' and status['last_scan_ok'] and status['last_publish_ok']
assert status['code_market_strength_hash']==status['snapshot_market_strength_hash']==M.IMPLEMENTATION_HASH
html=get('/dashboard.html').decode('utf8');packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip());brief=ui_payload.unpack(packet);token=brief['ui_generation']
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'));M.validate(s)
assert token==status['ui_generation'];assert brief['market_strength']==s['market_strength']
by={r['code']:r for r in s['stocks']+s['coverage_catalog']}
for r in brief['stocks']+brief['coverage_catalog']:assert r['market_strength']==M.brief(by[r['code']]['market_strength'])
for b in brief['board_catalog']:
 m=next(x['market_strength'] for x in s['board_catalog'] if x['id']==b['id'])
 for k,v in M.brief(m).items():assert b['market_strength'][k]==v
focus=s['market_strength']['stocks']['focus'];candidates=list(dict.fromkeys(focus[:2]+[c for c in focus if by[c]['market_strength']['emotion_strong'] and not by[c]['market_strength']['trend_strong']][:1]))
for code in candidates:
 item=json.loads(get('/__ui/detail?'+urlencode(dict(version=token,kind='stock',id=code))))
 assert item['version']==token and item['item']['market_strength']==by[code]['market_strength']
for identity in s['market_strength']['boards']['focus'][:2]:
 item=json.loads(get('/__ui/detail?'+urlencode(dict(version=token,kind='board',id=identity))))
 assert item['version']==token and item['item']['market_strength']==next(b['market_strength'] for b in s['board_catalog'] if b['id']==identity)
request=Request(base+'/__ui/export',data=json.dumps(dict(version=token,codes=focus,contexts={})).encode(),headers={'Content-Type':'application/json'},method='POST')
raw=urlopen(request,timeout=90).read();(out/'当前强势.csv').write_bytes(raw)
exported=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));assert [r['代码'] for r in exported]==focus
for r in exported:
 m=by[r['代码']]['market_strength']
 for field,axis in [('趋势分','trend'),('情绪分','emotion')]:assert (float(r[field]) if r[field] else None)==m[axis+'_score']
 assert r['规则版本']==M.VERSION and r['UI版本']==token and json.loads(r['完整模型依据'])==m
phases={phase:sum(r['market_strength']['phase']==phase for r in by.values() if r['market_strength']['focus']) for phase in ('启动','推进','回踩整理','转弱',None)}
result=dict(pid=status['pid'],runtime_hash=status['code_market_strength_hash'],version=M.VERSION,data_version=status['data_version'],ui_generation=token,quote_capture_at=s['quote_capture_at'],published_at=status['last_publish_at'],counts=s['market_strength']['counts'],board_counts=s['market_strength']['board_counts'],coverage=s['market_strength']['coverage'],focus_phases=phases,stock_details=candidates,export_rows=len(exported),csv_sha256=hashlib.sha256(raw).hexdigest(),all_summary_scores_match=True)
(out/'live_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');(out/'post_publish_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False))
