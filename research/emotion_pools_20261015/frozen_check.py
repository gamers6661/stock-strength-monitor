"""Freeze acquisition, native bars and relay evidence, compare unrelated models."""
import copy,gzip,hashlib,json,sqlite3,sys,time
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,emotion_relay as E,relay_history as H,relay_data as D,relay_cycles as C,relay_regulation as R,datafeed,strength
OUT=Path(__file__).resolve().parent
def read(p):
    with gzip.open(p,'rt',encoding='utf-8') as f:return json.load(f)
def write(p,v):
    with gzip.open(p,'wt',encoding='utf-8',compresslevel=1) as f:json.dump(v,f,ensure_ascii=False)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
frozen=OUT/'frozen_inputs.json.gz'
if frozen.exists():
    v=read(frozen);s=v['snapshot'];q=v['quotes'];hist=v['histories'];cal=v['calendar'];e=v['evidence'];now=datetime.fromisoformat(v['now'])
else:
    s=read(OUT/'baseline/snapshot.json.gz');rows=s['stocks']+s.get('coverage_catalog',[])
    with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions/2026-10-15.jsonl.gz','rt',encoding='utf-8') as f:
        a=next(v for line in f if (v:=json.loads(line))['captured_at'][:19]==s['quote_capture_at'][:19])
    q={x[0]:dict(zip(a['fields'][1:],x[1:])) for x in a['rows']}
    conn=sqlite3.connect(config.KLINE_DB);hist={r['code']:datafeed.load_kline(conn,'kline','code',r['code'],limit=160) for r in rows};conn.close()
    cal=strength.trading_calendar({c:strength.completed(v) for c,v in hist.items()});now=datetime.now();day=now.date().isoformat();dates=[d for d in cal if d<day]
    codes={r['code']:r for r in rows};e=H.load(codes,dates[-30:],dates,day,fetch=False);H.index(e)
    e['regulation']=R.load(C.focus(e,codes),dates+[day],now,fetch=False)
    e['current_pool']=D.fetch_pool(day);D.write(D.root()/'current_pool.json',e['current_pool'])
    write(frozen,dict(snapshot=s,quotes=q,histories=hist,calendar=cal,evidence=e,now=str(now)))
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows}
before=[(r['code'],digest(r.get('ma_trend')),digest(r.get('market_strength'))) for r in rows]
bd=[(b['id'],digest(b.get('member_codes')),digest(b.get('market_strength')),digest(b.get('index_trend')),digest(b.get('index_current'))) for b in s['board_catalog']]
ranks={b['id']:(b['stock_ranking']['all'],b['stock_ranking']['trend']) for b in s['board_catalog'] if b.get('stock_ranking')}
start=time.monotonic();E.attach(s,q,pool,hist,cal,now=now,evidence=e,fetch=False,persist=False);E.validate(s)
assert before==[(r['code'],digest(r.get('ma_trend')),digest(r.get('market_strength'))) for r in rows]
assert bd==[(b['id'],digest(b.get('member_codes')),digest(b.get('market_strength')),digest(b.get('index_trend')),digest(b.get('index_current'))) for b in s['board_catalog']]
for k,v in ranks.items():assert tuple(v)==(s['emotion_relay']['rankings'][k]['all'],s['emotion_relay']['rankings'][k]['trend'])
for name in ('ma_trend.py','ma_trend_ui.js','board_stock_rank.py'):assert (ROOT/name).read_bytes()==(OUT/'baseline'/name).read_bytes(),name
m=s['emotion_relay'];write(OUT/'frozen_output.json.gz',s)
report=dict(version=m['version'],hash=m['implementation_hash'],source=m['source_at'],asof=m['history_asof'],now=str(now),seconds=round(time.monotonic()-start,2),unchanged=['MA source/model','legacy scores','board members/index models','default/trend member ranks'],
    cap_strength_coverage=m['pools']['strength_coverage'],cap_count=len(m['lists']['sealed']),groups={k:len(v) for k,v in m['pools']['groups'].items()},
    caps=[dict(code=c,name=pool[c]['name'],height=pool[c]['emotion_relay']['height'],strength=pool[c]['emotion_relay']['cap_strength']) for c in m['lists']['sealed']],
    broken=[dict(code=c,name=pool[c]['name'],feedback=pool[c]['emotion_relay']['feedback_pct'],event=pool[c]['emotion_relay']['break_watch']) for c in m['lists']['broken']],promotion=m['promotion'])
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('caps','broken','promotion')},ensure_ascii=False),flush=True)
print('caps',[(r['code'],r['name'],r['height'],r['strength']['height_rank'],r['strength']['reopen_count']) for r in report['caps']],flush=True)
print('broken',[(r['code'],r['name'],r['event']['date'],r['event']['height'],r['event']['labels']) for r in report['broken']],flush=True)
