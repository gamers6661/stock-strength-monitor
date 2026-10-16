"""Read-only independent acceptance. Writes evidence only under research."""
import copy, csv, hashlib, io, json, sys
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen, Request
sys.path.insert(0, str(Path.cwd()))
import config, market_strength as M, ui_payload
from test_market_strength import fixture

ROOT = Path.cwd()
DIR = Path(__file__).parent
BASE = DIR.parent / 'baseline'
OUT = DIR / 'owner_round2'
OUT.mkdir(exist_ok=True)
evidence = {}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest().lower()
def digest(x):
    return hashlib.sha256(json.dumps(json.loads(json.dumps(x)), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
def save():
    (OUT/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),'utf8')

manifest=json.loads((BASE/'manifest.json').read_text('utf8'))
bad=[p for p,h in manifest.items() if sha(BASE/p)!=h.lower()]
rework=json.loads((DIR/'backup_manifest.json').read_text('utf8'))
rework_bad=[r['file'] for r in rework if sha(DIR/'baseline'/r['file'])!=r['sha256'].lower()]
evidence['files']=dict(original_backup_count=len(manifest),original_backup_mismatches=bad,rework_backup_mismatches=rework_bad,
    config_unchanged=config.ROOT.joinpath('config.py').read_bytes()==(DIR/'baseline/config.py').read_bytes(),
    current_sources={p:sha(ROOT/p) for p in ('market_strength.py','radar_ui.js','ui_payload.py','serve.py','test_market_strength_rework.py')},
    instruction_sha256=sha(DIR.parent/'负责人执行指令.md'))
assert not bad and not rework_bad and evidence['files']['config_unchanged']
print('FILES',evidence['files'],flush=True)

raw=(BASE/'frozen_complete_inputs.json').read_bytes(); f=json.loads(raw)
s=json.loads((BASE/'cache/snapshot.json').read_text('utf8'))
old=json.loads((DIR.parent/'comparison.json').read_text('utf8'))
members=digest([b['member_codes'] for b in s['board_catalog']])
indices=digest([{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']])
M.attach(s,f['quotes'],f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(f['now']))
M.validate(s)
rows=s['stocks']+s['coverage_catalog']
sd=[r['code'] for r in rows if digest(r['market_strength'])!=digest(old['stocks'][r['code']]['new'])]
bd=[b['id'] for b in s['board_catalog'] if digest(b['market_strength'])!=digest(old['boards'][b['id']])]
evidence['frozen']=dict(stocks=len(rows),boards=len(s['board_catalog']),stock_differences=sd,board_differences=bd,
    inputs_unchanged=raw==(BASE/'frozen_complete_inputs.json').read_bytes(),
    members_unchanged=members==digest([b['member_codes'] for b in s['board_catalog']]),
    indices_unchanged=indices==digest([{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']]))
assert not sd and not bd and all(evidence['frozen'][k] for k in ('inputs_unchanged','members_unchanged','indices_unchanged'))
print('FROZEN',evidence['frozen'],flush=True);save()
del s,f,old,raw

s,q,p,h,c,n=fixture()
s['session']='午间休市'
for v in q.values():v.update(price=110.,open=100.,high=110.,low=100.,change_pct=10.,quote_at='2026-10-13 11:31:11')
M.attach(s,q,p,h,c,now=datetime(2026,10,13,12));M.validate(s)
previous=copy.deepcopy(s)
for v in q.values():v['quote_at']='2026-10-13 12:30:00'
M.attach(s,q,p,h,c,now=datetime(2026,10,13,12,45),previous=previous);M.validate(s)
after=copy.deepcopy(s)
s['session']='午盘'
M.attach(s,q,p,h,c,now=datetime(2026,10,13,13,5),previous=previous);M.validate(s)
evidence['lunch_reference_reproduction']=dict(
    previous_stock_counts=previous['market_strength']['counts'],previous_board_counts=previous['market_strength']['board_counts'],
    previous_model=previous['stocks'][0]['market_strength'],
    lunch_stock_counts=after['market_strength']['counts'],lunch_board_counts=after['market_strength']['board_counts'],
    lunch_model=after['stocks'][0]['market_strength'],lunch_mode=after['market_strength']['mode'],
    afternoon_stale_counts=s['market_strength']['counts'])
assert previous['market_strength']['counts']['focus']==10 and after['market_strength']['counts']['focus']==0
assert s['market_strength']['counts']['focus']==0
print('LUNCH reproduction: valid morning 10 stocks / 1 board -> lunch 0 / 0, despite previous supplied',flush=True);save()

base='http://127.0.0.1:8848'
def get(path):return urlopen(base+path,timeout=90).read()
status=json.loads(get('/__status'))
html=get('/dashboard.html').decode('utf8')
packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip())
brief=ui_payload.unpack(packet);token=brief['ui_generation']
full=ui_payload.full(token);M.validate(full)
assert status['code_market_strength_hash']==status['snapshot_market_strength_hash']==M.IMPLEMENTATION_HASH
assert status['ui_generation']==token
by={r['code']:r for r in full['stocks']+full['coverage_catalog']}
boards={b['id']:b for b in full['board_catalog']}
def export(payload):
    return urlopen(Request(base+'/__ui/export',data=json.dumps(dict(version=token,**payload)).encode(),headers={'Content-Type':'application/json'}),timeout=90).read()
codes=full['market_strength']['stocks']['focus'];content=export(dict(codes=codes,contexts={}))
(OUT/'stocks_api.csv').write_bytes(content)
records=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
assert [r['代码'] for r in records]==codes
assert all(json.loads(r['完整模型依据'])==by[r['代码']]['market_strength'] and r['UI版本']==token for r in records)
export_counts={}
for kind in ('industry','theme'):
    ids=[i for i in full['market_strength']['boards']['sorts']['combined'] if i in full['market_strength']['boards']['focus'] and boards[i]['type']==kind]
    content=export(dict(kind='board',ids=ids));(OUT/(kind+'_api.csv')).write_bytes(content)
    records=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
    assert [r['ID'] for r in records]==ids
    assert all(json.loads(r['完整模型依据'])==boards[r['ID']]['market_strength'] and r['UI版本']==token for r in records)
    export_counts[kind]=len(records)
evidence['live']=dict(pid=status['pid'],implementation_hash=M.IMPLEMENTATION_HASH,ui_generation=token,
    data_version=status['data_version'],quote_capture=full['quote_capture_at'],session=full['session'],
    counts=full['market_strength']['counts'],board_counts=full['market_strength']['board_counts'],coverage=full['market_strength']['coverage'],
    stock_csv_rows=len(codes),board_csv_rows=export_counts)
expectations={}
for name in ('染料','影视院线'):
    b=next(b for b in boards.values() if b['name']==name)
    member=set(b['member_codes'])
    expectations[name]=dict(id=b['id'],all=[c for c in full['market_strength']['stocks']['sorts']['combined'] if c in member])
    for axis in ('trend','emotion'):
        expectations[name][axis]=[c for c in full['market_strength']['stocks']['sorts'][axis] if c in member and c in full['market_strength']['stocks'][axis]]
evidence['member_expectations']=expectations
(OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),'utf8')
save(); print('LIVE',evidence['live'],flush=True)
