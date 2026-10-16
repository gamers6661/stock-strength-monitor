"""Same-input comparison. Freshly backfilled bars stop before the frozen quote minute."""
import ast,copy,gzip,importlib.util,json,sqlite3,sys,tempfile,time
from collections import Counter
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,strength,ma_trend as T,close_monitor as C
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline'
with gzip.open(BASE/'snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
day=s['quote_capture_at'][:10];asof=s['strength_model']['asof'];now=datetime.fromisoformat(s['quote_capture_at'])
with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions'/(day+'.jsonl.gz'),'rt',encoding='utf-8') as f:
    record=next(r for line in f if (r:=json.loads(line))['captured_at'][:19]==s['quote_capture_at'][:19])
with gzip.open(BASE/'acquisition.json.gz','wt',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False)
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
pool={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
conn=sqlite3.connect((BASE/'market.db').resolve().as_uri()+'?mode=ro',uri=True)
h={c:datafeed.load_kline(conn,'kline','code',c,limit=160) for c in pool};conn.close()
cal=strength.trading_calendar({c:strength.completed(v) for c,v in h.items()})
old_params=next(n.value for n in ast.parse((BASE/'config.py').read_text(encoding='utf-8')).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MA_TREND' for t in n.targets))
current=config.MA_TREND;config.MA_TREND=eval(compile(ast.Expression(old_params),'frozen-parameters','eval'),{'__builtins__':{}},{})
spec=importlib.util.spec_from_file_location('before_recovery',BASE/'ma_trend.py');before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before);config.MA_TREND=current
tested=0;candidates=[]
for code,row in pool.items():
    bars=[b for b in h[code] if b['date']<=asof]
    if not bars or bars[-1]['date']!=asof:continue
    limit=10 if not row['name'].upper().startswith(('ST','*ST')) else None
    a=before.daily(bars,cal,limit);b=T.daily(bars,cal,limit)
    assert a=={k:v for k,v in b.items() if k!='recovery_candidate'},code
    if not a['pending']:tested+=1
    if (b.get('recovery_candidate') or {}).get('active'):candidates.append(dict(code=code,name=row['name'],event=b['recovery_candidate']))
print('daily comparison',tested,'candidate events',len(candidates),flush=True)
cache=json.loads((BASE/'minutes.json').read_text(encoding='utf-8'))
def past(data):
    return {c:[b for b in bars if b['at']<str((quotes.get(c) or {}).get('quote_at') or (quotes.get(c) or {}).get('ts') or '')[:16]] for c,bars in data.items()}
old_minutes=past(cache.get('stocks') or {})
prior=copy.deepcopy(s);T.attach(prior,quotes,pool,h,cal,now=now,minute_data=old_minutes,fetch_minutes=False)
needed=[r['code'] for r in prior['stocks']+prior.get('coverage_catalog',[]) if (r.get('ma_trend') or {}).get('minute_needed')]
stats={}
if (OUT/'backfilled_minutes.json').exists():
    fresh=json.loads((OUT/'backfilled_minutes.json').read_text(encoding='utf-8'))
    stats=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf-8'))['fetch']
    for c in needed:fresh[c]=C._certify_no_trade_gaps(c,day,fresh.get(c) or [])
else:
    with tempfile.TemporaryDirectory(prefix='minute-backfill-proof-') as d:
        C.MINUTE_DIR=Path(d)
        (C.MINUTE_DIR/(day+'.json')).write_text(json.dumps(dict(day=day,stocks=old_minutes),ensure_ascii=False),encoding='utf-8')
        fresh=C._get_minutes(needed,day,{c:quotes[c].get('quote_at') or quotes[c].get('ts') for c in needed},request_stats=stats)
(OUT/'backfilled_minutes.json').write_text(json.dumps(fresh,ensure_ascii=False),encoding='utf-8')
after=copy.deepcopy(s);T.attach(after,quotes,pool,h,cal,now=now,minute_data=past(fresh),fetch_minutes=False);T.validate(after)
def models(snap):return {r['code']:r['ma_trend'] for r in snap['stocks']+snap.get('coverage_catalog',[])}
a=models(prior);b=models(after)
changes=[dict(code=c,name=pool[c]['name'],before=a[c]['status'],after=b[c]['status'],before_reason=a[c]['reason'],after_reason=b[c]['reason'],coverage=b[c].get('minute_coverage')) for c in needed if a[c]['status']!=b[c]['status']]
legacy=lambda snap:[(r['code'],r.get('market_strength'),r.get('stock_strength_score')) for r in snap['stocks']+snap.get('coverage_catalog',[])]
assert legacy(s)==legacy(after)
report=dict(version=T.VERSION,hash=T.IMPLEMENTATION_HASH,source=s['quote_capture_at'],asof=asof,
    daily_tested=tested,all_original_daily_stages_origins_platforms_exits_unchanged=True,
    candidate_count=len(candidates),candidates=candidates,minute_needed=len(needed),fetch=stats,
    before_status=dict(Counter(m['status'] for m in a.values())),after_status=dict(Counter(m['status'] for m in b.values())),
    resolved_support_pending=sum(a[c]['status']=='支撑过程待核验' and b[c]['status']!='支撑过程待核验' for c in needed),
    remaining=[dict(code=c,name=pool[c]['name'],reason=m['reason']) for c,m in b.items() if m['status']=='支撑过程待核验'],
    changes=changes,legacy_scores_and_emotion_unchanged=True,
    minute_evidence_cutoff='strictly before each frozen quote minute; later intraminute prices excluded')
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('candidates','changes','remaining')},ensure_ascii=False),flush=True)
print('remaining',report['remaining'],flush=True)
