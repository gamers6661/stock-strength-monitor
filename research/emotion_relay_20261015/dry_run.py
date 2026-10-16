import gzip,hashlib,json,sqlite3,sys,time
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import emotion_relay as E,datafeed,strength
OUT=Path(__file__).resolve().parent
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
with gzip.open(OUT/'baseline/acquisition.json.gz','rt',encoding='utf-8') as f:r=json.load(f)
quotes={x[0]:dict(zip(r['fields'][1:],x[1:])) for x in r['rows']}
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows}
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
before=[(r['code'],digest(r.get('ma_trend')),digest(r.get('market_strength'))) for r in rows]
boards_before=[(b['id'],digest(b.get('member_codes')),digest(b.get('market_strength')),digest(b.get('index_trend')),digest(b.get('index_current'))) for b in s['board_catalog']]
conn=sqlite3.connect(OUT/'baseline/market.db');hist={c:datafeed.load_kline(conn,'kline','code',c,limit=160) for c in pool};conn.close()
cal=strength.trading_calendar({c:strength.completed(v) for c,v in hist.items()})
evidence=json.loads((OUT/'evidence.json').read_text(encoding='utf-8'));start=time.monotonic()
E.attach(s,quotes,pool,hist,cal,now=datetime.fromisoformat(s['quote_capture_at']),evidence=evidence,persist=False);E.validate(s)
assert before==[(r['code'],digest(r.get('ma_trend')),digest(r.get('market_strength'))) for r in rows]
assert boards_before==[(b['id'],digest(b.get('member_codes')),digest(b.get('market_strength')),digest(b.get('index_trend')),digest(b.get('index_current'))) for b in s['board_catalog']]
for name in ('ma_trend.py','ma_trend_ui.js','board_stock_rank.py'):
    assert (ROOT/name).read_bytes()==(OUT/'baseline'/name).read_bytes(),name
meta=s['emotion_relay'];report={k:v for k,v in meta.items() if k not in ('rankings','boards')}
report.update(seconds=round(time.monotonic()-start,3),ma_and_legacy_scores_unchanged=True,
    board_members_and_index_models_unchanged=True,ma_source_and_rank_source_unchanged=True,
    leaders=[dict(code=c,name=pool[c]['name'],model=pool[c]['emotion_relay']) for c in meta['lists']['leaders']],
    continuation=[dict(code=c,name=pool[c]['name'],model=pool[c]['emotion_relay']) for c in meta['lists']['continuation']])
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ('version','implementation_hash','source_at','mode','coverage','state','highest_completed','highest_live','seconds','ma_and_legacy_scores_unchanged')},ensure_ascii=False),flush=True)
print('lists',{k:len(v) for k,v in meta['lists'].items()},flush=True)
print('leaders',[(c,pool[c]['name'],pool[c]['emotion_relay']['height'],pool[c]['emotion_relay']['roles']) for c in meta['lists']['leaders'][:15]],flush=True)
