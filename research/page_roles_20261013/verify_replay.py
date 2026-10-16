"""Frozen A/B and real saved acquisition replay; quote timestamps are never changed."""
import ast,copy,gzip,hashlib,json,sys,types
from datetime import datetime,timedelta
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import market_strength as M
import config

O=Path(__file__).parent
B=Path('research/market_strength_v1_20261013/baseline')
raw=(B/'frozen_complete_inputs.json').read_bytes();f=json.loads(raw)
old_p=next(ast.literal_eval(n.value) for n in ast.parse((O/'baseline/config.py').read_text('utf8')).body
           if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MARKET_STRENGTH' for t in n.targets))
old=types.ModuleType('before');old.__file__=str(O/'baseline/market_strength.py')
exec((O/'baseline/market_strength.py').read_text('utf8').replace('P = config.MARKET_STRENGTH','P = '+repr(old_p)),old.__dict__)
base=json.loads((B/'cache/snapshot.json').read_text('utf8'));before=copy.deepcopy(base);after=copy.deepcopy(base)
args=(f['quotes'],f['pool'],f['histories'],f['calendar'])
old.attach(before,*args,now=datetime.fromisoformat(f['now']))
M.attach(after,*args,now=datetime.fromisoformat(f['now']));M.validate(after)
def models(s):return {r['code']:r['market_strength'] for r in s['stocks']+s['coverage_catalog']}
a,b=models(before),models(after)
differences=[(c,k,a[c].get(k),b[c].get(k)) for c in a for k in ('trend_score','emotion_score','focus','trend_strong','emotion_strong') if a[c].get(k)!=b[c].get(k)]
assert not differences,differences[:10]
assert [x['member_codes'] for x in before['board_catalog']]==[x['member_codes'] for x in after['board_catalog']]
assert [(x['market_strength']['trend_score'],x['market_strength']['emotion_score']) for x in before['board_catalog']]==[(x['market_strength']['trend_score'],x['market_strength']['emotion_score']) for x in after['board_catalog']]
frozen=dict(input_hash=hashlib.sha256(raw).hexdigest(),at=f['now'],before_counts=before['market_strength']['counts'],after_counts=after['market_strength']['counts'],score_differences=differences,
    phases_changed=sum(a[c]['phase']!=b[c]['phase'] for c in a),membership_unchanged=True)
(O/'frozen_comparison.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(frozen,ensure_ascii=False),flush=True)
# Replay the exact source acquisition times, using strictly completed pre-today history.
live=json.loads((O/'baseline/cache/snapshot.json').read_text('utf8'))
capture=datetime.fromisoformat(live['quote_capture_at'])
source_path=Path('cache/intraday_history/acquisitions')/(capture.date().isoformat()+'.jsonl.gz')
records=[]
with gzip.open(source_path,'rt',encoding='utf8') as stream:
    for line in stream:
        r=json.loads(line);at=datetime.fromisoformat(r['captured_at'])
        if capture-timedelta(minutes=40)<=at<=capture:records.append(r)
records.sort(key=lambda r:r['captured_at'])
assert records and records[-1]['captured_at']==live['quote_capture_at'],[r['captured_at'] for r in records]
if '--last-two' in sys.argv:
    target=capture-timedelta(minutes=15)
    prior=min(records[:-1],key=lambda r:abs((datetime.fromisoformat(r['captured_at'])-target).total_seconds()))
    records=[prior,records[-1]]
previous=None;replayed=[]
for record in records:
    quotes={str(row[0]):dict(zip(record['fields'][1:],row[1:])) for row in record['rows']}
    snap=copy.deepcopy(live);snap['session']=record['session'];snap['quote_capture_at']=record['captured_at']
    for row in snap['stocks']+snap['coverage_catalog']:
        if row['code'] in quotes:row.update(quotes[row['code']])
        if record is not records[-1]:row['intraday_risk_flags']=[]
    M.attach(snap,quotes,f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(record['captured_at']),previous=previous)
    M.validate(snap)
    replayed.append(dict(captured_at=record['captured_at'],source_at=snap['direction_changes']['source_at'],from_at=snap['direction_changes']['from_at'],
        counts=snap['market_strength']['counts'],turning=snap['direction_changes']['items']))
    previous=snap
    print('Replayed '+record['captured_at'],flush=True)
assert raw==(B/'frozen_complete_inputs.json').read_bytes()
(O/'real_replay.json').write_text(json.dumps(dict(acquisition_hash=hashlib.sha256(source_path.read_bytes()).hexdigest(),records=replayed),ensure_ascii=False,indent=2),'utf8')
(O/'validated_snapshot.json').write_text(json.dumps(previous,ensure_ascii=False,separators=(',',':')),'utf8')
print(json.dumps(dict(replayed=len(records),last=replayed[-1],version=M.VERSION,hash=M.IMPLEMENTATION_HASH),ensure_ascii=False),flush=True)
if '--publish' in sys.argv:
    import make_dashboard
    config.atomic_write_text(config.SNAPSHOT_JSON,json.dumps(previous,ensure_ascii=False,separators=(',',':')))
    assert make_dashboard.build(previous)
    print('Published verified snapshot with original source times.',flush=True)
