"""Same-input acceptance and optional guarded publication; no quote collection."""
import copy,gzip,json,sqlite3,sys,time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,ma_trend as T,strength

OUT=Path(__file__).resolve().parent


def projection(s):
    return dict(model=s['market_strength'],
        stocks=[(r['code'],r['market_strength']['trend_score'],r['market_strength']['emotion_score'],
                 r.get('stock_strength_score'),r.get('trend_tier'),r['market_strength'].get('phase')) for r in s['stocks']+s.get('coverage_catalog',[])],
        boards=[(b['id'],b['member_codes'],b['market_strength']['trend_score'],b['market_strength']['emotion_score'],
                 b.get('index_quote'),b.get('index_trend'),b.get('index_current')) for b in s['board_catalog']])


def run(publish=False):
    if publish:
        s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'));db=config.KLINE_DB
    else:
        s=json.loads(gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf8').read());db=OUT/'baseline/market.db'
    before=copy.deepcopy(projection(s))
    source=s.get('market_strength_close_input') if s.get('session')=='已收盘' else s.get('market_strength_morning_input')
    q=(source or {}).get('quotes') or {r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
    p={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
    con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
    h={c:datafeed.load_kline(con,'kline','code',c,limit=160) for c in p};con.close()
    cal=strength.trading_calendar({c:strength.completed(v) for c,v in h.items()})
    t=time.perf_counter();previous=copy.deepcopy({'ma_trend':s.get('ma_trend'),'stocks':[{'code':r['code'],'ma_trend':r.get('ma_trend')} for r in s['stocks']+s.get('coverage_catalog',[])]})
    frozen_minutes=OUT/'frozen_minutes.json'
    if not publish and not frozen_minutes.exists():
        import close_monitor
        frozen_minutes.write_text(json.dumps(close_monitor._load_minute_cache(s['quote_capture_at'][:10]).get('stocks',{}),ensure_ascii=False),encoding='utf8')
    minutes=None if publish else json.loads(frozen_minutes.read_text(encoding='utf8'))
    T.attach(s,q,p,h,cal,now=datetime.fromisoformat(s['quote_capture_at']),previous=previous,fetch_minutes=publish,minute_data=minutes)
    cold=time.perf_counter()-t;T.validate(s);assert before==projection(s)
    result=dict(seconds=round(cold,3),version=T.VERSION,implementation_hash=T.IMPLEMENTATION_HASH,
                snapshot_generated_at=s['generated_at'],counts=s['ma_trend']['counts'],
                exited=len(s['ma_trend']['exited']),repair=len(s['ma_trend']['repair']),pending=len(s['ma_trend']['pending']),
                minute_needed=s['ma_trend']['minute_needed'],minute_requested=s['ma_trend']['minute_requested'],
                legacy_stock_scores_and_tiers_unchanged=True,emotion_scores_unchanged=True,
                board_members_and_index_fields_unchanged=True)
    (OUT/('publication.json' if publish else 'frozen_comparison.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    if publish:
        import make_dashboard
        config.atomic_write_text(config.SNAPSHOT_JSON,json.dumps(s,ensure_ascii=False,separators=(',',':')))
        make_dashboard.build(s)
    else:
        with gzip.open(OUT/'frozen_result.json.gz','wt',encoding='utf8',compresslevel=1) as f:json.dump(s,f,ensure_ascii=False,separators=(',',':'))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    if '--publish' in sys.argv:
        with config.pipeline_guard():run(True)
    else:run(False)
