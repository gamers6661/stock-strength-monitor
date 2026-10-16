import copy,gzip,json,sqlite3,sys,time
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,strength,ma_trend,board_stock_rank
OUT=Path(__file__).resolve().parent
def projection(s):
    return {'stocks':[(r['code'],r.get('market_strength'),r.get('stock_strength_score'),r.get('trend_tier')) for r in s['stocks']+s.get('coverage_catalog',[])],
        'boards':[(b['id'],b['member_codes'],b.get('market_strength'),b.get('index_quote'),b.get('index_trend'),b.get('index_current')) for b in s['board_catalog']]}
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
before=copy.deepcopy(projection(s));old=copy.deepcopy(s['ma_trend'])
pool={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
with gzip.open(OUT/'baseline/acquisition.json.gz','rt',encoding='utf-8') as f:record=json.load(f)
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
con=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True)
h={c:datafeed.load_kline(con,'kline','code',c,limit=160) for c in pool};con.close()
cal=strength.trading_calendar({c:strength.completed(v) for c,v in h.items()})
minutes=json.loads((OUT/'frozen_minutes.json').read_text(encoding='utf-8'))
started=time.perf_counter();ma_trend.attach(s,quotes,pool,h,cal,now=datetime.fromisoformat(s['quote_capture_at']),minute_data=minutes,fetch_minutes=False)
ma_trend.validate(s);assert before==projection(s)
cases=[dict(code=r['code'],name=r['name'],ma_trend=r['ma_trend']) for r in pool.values() if r['name'] in ('贝瑞基因','澳洋健康')]
added=set(s['ma_trend']['current'])-set(old['current'])
report=dict(version=ma_trend.VERSION,hash=ma_trend.IMPLEMENTATION_HASH,source=s['quote_capture_at'],seconds=round(time.perf_counter()-started,2),
    old_counts=old['counts'],new_counts=s['ma_trend']['counts'],advance=len(s['ma_trend']['advance']),pending=len(s['ma_trend']['pending']),
    legacy_scores_emotion_members_and_index_unchanged=True,full_board_member_ranks_verified=True,
    total_added=len(added),added_stages={str(n):sum(pool[c]['ma_trend']['stage']==n for c in added) for n in (5,10,20)},
    representative_changes=[dict(code=c,name=pool[c]['name'],stage=pool[c]['ma_trend']['stage'],status=pool[c]['ma_trend']['status'],origin=(pool[c]['ma_trend']['origin'] or {}).get('date')) for c in sorted(added)[:20]],cases=cases)
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
# No frozen output is published. Production acceptance must come from a new live scan.
print(json.dumps({k:v for k,v in report.items() if k not in ('cases','representative_changes')},ensure_ascii=False))
for case in cases:
    m=case['ma_trend'];print(case['name'],m['stage'],m['status'],m['reason'],(m['origin'] or {}).get('date'))
