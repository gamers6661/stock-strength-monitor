import ast,copy,difflib,gzip,importlib.util,json,sqlite3,sys,inspect,hashlib
from collections import Counter
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,strength,ma_trend as T
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline'
with gzip.open(BASE/'snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
# Quantitative replay only needs model inputs, not the duplicated reports,
# charts and research archives bundled in a live snapshot.
s={**{k:s[k] for k in ('quote_capture_at','generated_at','session','strength_model')},
   **{group:[{k:r[k] for k in ('code','name','quote_at','ts','market_strength') if k in r} for r in s.get(group,[])] for group in ('stocks','coverage_catalog')},
   'board_catalog':[{k:b[k] for k in ('id','name','type','member_codes') if k in b} for b in s['board_catalog']]}
with gzip.open(BASE/'acquisition.json.gz','rt',encoding='utf-8') as f:record=json.load(f)
q={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
pool={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
conn=sqlite3.connect((BASE/'market.db').resolve().as_uri()+'?mode=ro',uri=True)
h={c:datafeed.load_kline(conn,'kline','code',c,limit=160) for c in pool};conn.close()
cal=strength.trading_calendar({c:strength.completed(v) for c,v in h.items()})
expr=next(n.value for n in ast.parse((BASE/'config.py').read_text(encoding='utf-8')).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MA_TREND' for t in n.targets))
current=config.MA_TREND;config.MA_TREND=eval(compile(ast.Expression(expr),'baseline-config','eval'),{'__builtins__':{}},{})
spec=importlib.util.spec_from_file_location('before_current',BASE/'ma_trend.py');before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before);config.MA_TREND=current
tested=0;asof=s['strength_model']['asof'];daily_changes=[]
for code,r in pool.items():
    bars=[b for b in h[code] if b['date']<=asof]
    if not bars or bars[-1]['date']!=asof:continue
    limit=10 if not r['name'].upper().startswith(('ST','*ST')) else None
    a=before.daily(bars,cal,limit);b=T.daily(bars,cal,limit)
    assert {k:v for k,v in a.items() if k!='recovery_candidate'}=={k:v for k,v in b.items() if k!='recovery_candidate'},code
    if not a['pending']:tested+=1
    ca=a.get('recovery_candidate') or {};cb=b.get('recovery_candidate') or {}
    if ca.get('active')!=cb.get('active'):daily_changes.append(dict(code=code,name=r['name'],date=cb.get('date'),before=ca.get('state'),after=cb.get('state'),age=cb.get('age_sessions')))
minutes=json.loads((BASE/'minutes.json').read_text(encoding='utf-8'))['stocks']
# Never use prices from a minute later than the frozen quote minute.
minutes={c:[b for b in bars if b['at']<str((q.get(c) or {}).get('quote_at') or (q.get(c) or {}).get('ts') or '')[:16]] for c,bars in minutes.items()}
now=datetime.fromisoformat(s['quote_capture_at']);a=copy.deepcopy(s);b=copy.deepcopy(s)
before.attach(a,q,pool,h,cal,now=now,minute_data=minutes,fetch_minutes=False)
T.attach(b,q,pool,h,cal,now=now,minute_data=minutes,fetch_minutes=False);T.validate(b)
def models(snap):return {r['code']:r['ma_trend'] for r in snap['stocks']+snap.get('coverage_catalog',[])}
am=models(a);bm=models(b);old={c for c,m in am.items() if (m.get('recovery_candidate') or {}).get('active')};new=set(b['ma_trend']['recovery_candidates'])
assert all(bm[c]['recovery_candidate']['age_sessions']<=5 and not bm[c]['pending'] for c in new)
assert [r.get('market_strength') for r in s['stocks']]==[r.get('market_strength') for r in b['stocks']]
assert all(a['stock_board_ranking']['all'][k]==b['stock_board_ranking']['all'][k] for k in ('all','trend','emotion'))
report=dict(version=T.VERSION,hash=T.IMPLEMENTATION_HASH,daily_source_hash=hashlib.sha256(inspect.getsource(T.daily).encode()).hexdigest(),source=s['quote_capture_at'],asof=asof,daily_tested=tested,
    original_daily_stages_origins_platforms_exits_unchanged=True,emotion_scores_and_numeric_rank_order_unchanged=True,
    window_sessions=T.P['limit_recovery_candidate_days'],daily_changes=daily_changes,
    old_current=len(old),new_current=len(new),
    removed=[dict(code=c,name=pool[c]['name'],old_event=am[c]['recovery_candidate'],new_event=bm[c].get('recovery_candidate'),status=bm[c]['status']) for c in sorted(old-new)],
    current=[dict(code=c,name=pool[c]['name'],event=bm[c]['recovery_candidate'],quote_at=bm[c]['quote_at']) for c in sorted(new)],
    historical_events_hidden_from_summary=sum(bool(m.get('recovery_candidate')) and 'recovery_candidate' not in T.brief(m) for m in bm.values()),
    no_new_module=True,minute_cutoff='strictly before frozen quote minute')
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
parts=[]
for p in BASE.iterdir():
    if p.suffix not in ('.py','.js','.html'):continue
    parts.extend(difflib.unified_diff(p.read_text(encoding='utf-8').splitlines(True),(ROOT/p.name).read_text(encoding='utf-8').splitlines(True),fromfile='before/'+p.name,tofile='after/'+p.name))
(OUT/'source.diff').write_text(''.join(parts),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('daily_changes','current','removed')},ensure_ascii=False),flush=True)
print('removed',[(x['code'],x['name'],(x['new_event'] or {}).get('state')) for x in report['removed']],flush=True)
