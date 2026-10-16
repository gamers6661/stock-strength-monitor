"""Evaluate immutable pre-change inputs without publishing or collecting quotes."""
import copy,gzip,json,sqlite3,sys,time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,strength,ma_trend
OUT=Path(__file__).resolve().parent

def projection(s):
    return {'stocks':[(r['code'],r.get('market_strength'),r.get('stock_strength_score'),r.get('trend_tier'))
            for r in s['stocks']+s.get('coverage_catalog',[])],
            'boards':[(b['id'],b['member_codes'],b.get('market_strength'),b.get('index_quote'),b.get('index_trend'),b.get('index_current'))
                      for b in s['board_catalog']]}

with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
before=copy.deepcopy(projection(s));old=copy.deepcopy(s['ma_trend'])
pool={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
archive=OUT/'baseline/acquisition.json.gz'
if archive.exists():
    with gzip.open(archive,'rt',encoding='utf-8') as f:record=json.load(f)
else:
    record=None
    with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions'/
                   (s['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf-8') as f:
        for line in f:
            candidate=json.loads(line)
            if candidate['captured_at'][:19]==s['quote_capture_at'][:19]:record=candidate;break
    assert record is not None,'Exact raw acquisition is required; never infer missing quote basis tags'
    with gzip.open(archive,'wt',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False)
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
con=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True)
h={c:datafeed.load_kline(con,'kline','code',c,limit=160) for c in pool};con.close()
cal=strength.trading_calendar({c:strength.completed(v) for c,v in h.items()})
minutes=json.loads((OUT/'frozen_minutes.json').read_text(encoding='utf-8'))
started=time.perf_counter()
ma_trend.attach(s,quotes,pool,h,cal,now=datetime.fromisoformat(s['quote_capture_at']),minute_data=minutes,fetch_minutes=False)
ma_trend.validate(s);assert before==projection(s)
meta=s['ma_trend'];old_ids=set(old['current']);new_ids=set(meta['current'])
result={'version':meta['version'],'implementation_hash':meta['implementation_hash'],
        'source_capture_at':s['quote_capture_at'],'seconds':round(time.perf_counter()-started,3),
        'old_counts':old['counts'],'new_counts':meta['counts'],
        'advance':len(meta['advance']),'displaced':len(meta['displaced']),
        'pending':len(meta['pending']),'startup_pending':len(meta['startup_pending']),
        'legacy_scores_emotion_members_and_index_unchanged':True,
        'removed':[{'code':c,'name':pool[c]['name'],'old_stage':next(n for n,v in old['lists'].items() if c in v),
                    'new_stage':pool[c]['ma_trend']['stage'],'reason':pool[c]['ma_trend']['reason'],
                    'status':pool[c]['ma_trend']['status']} for c in sorted(old_ids-new_ids)],
        'added':sorted(new_ids-old_ids)}
(OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
with gzip.open(OUT/'frozen_result.json.gz','wt',encoding='utf-8',compresslevel=1) as f:json.dump(s,f,ensure_ascii=False,separators=(',',':'))
print(json.dumps({k:v for k,v in result.items() if k not in ('removed','added')},ensure_ascii=False))
