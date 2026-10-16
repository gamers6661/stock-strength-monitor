"""逐行核对日线边界、11:30口径、历史前缀及每次实际输入留存。"""
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
snap=json.loads((ROOT/'cache/snapshot.json').read_text(encoding='utf-8'))
with gzip.open(OUT/'before_snapshot.json.gz','rt',encoding='utf-8') as stream:
    before=json.load(stream)
with gzip.open(OUT/'first_published_snapshot.json.gz','wt',encoding='utf-8') as stream:
    json.dump(snap,stream,ensure_ascii=False,separators=(',',':'))
allrows=snap['stocks']+snap.get('coverage_catalog',[])
daily_fields=('stock_strength_score','stock_strength_parts','stock_strength_percentile',
              'daily_attack_tier','daily_attack_stage','trend_online','trend_tier','signal_date','signal_day',
              'ma5','ma10','ma20','ret5','ret10','ret20')
old={r['code']:r for r in before['stocks']}; new={r['code']:r for r in snap['stocks']}
differences=[dict(code=c,fields=[k for k in daily_fields if old[c].get(k)!=new[c].get(k)])
             for c in sorted(old.keys()&new.keys()) if any(old[c].get(k)!=new[c].get(k) for k in daily_fields)]
history_before=(OUT/'before_intraday_history.jsonl').read_bytes()
history=(ROOT/'cache/intraday_history/2026-09-30.jsonl').read_bytes()
assert history.startswith(history_before),'旧历史被改写'
records=[json.loads(line) for line in history.decode('utf-8').splitlines() if line.strip()]
rawpath=ROOT/'cache/intraday_history/acquisitions/2026-09-30.jsonl.gz'
with gzip.open(rawpath,'rt',encoding='utf-8') as stream:
    raw=[json.loads(line) for line in stream]
available=[r for r in allrows if r.get('intraday_observation_available') is True]
assert all(r['intraday_judgment_at']=='2026-09-30 11:30:00' for r in available)
assert all(not r.get('attack_watch_candidate') and not r.get('current_strong_candidate') for r in allrows)
assert all((r['intraday_path']['last_at']==r['intraday_judgment_at']) for r in available)
boundary=snap['boundary_prices']['midday']['prices']
closing_differences=[dict(code=r['code'],boundary=boundary[r['code']]['price'],current=r['price']) for r in available
                     if r['code'] in boundary and abs(boundary[r['code']]['price']-r['price'])>1e-6]
result=dict(snapshot_at=snap['generated_at'],quote_capture_at=snap['quote_capture_at'],
    service=json.load(urlopen('http://127.0.0.1:8848/__status')),
    daily_comparison=dict(before_asof=before['strength_model']['asof'],after_asof=snap['strength_model']['asof'],
        same_codes=len(old.keys()&new.keys()),added=sorted(new.keys()-old.keys()),removed=sorted(old.keys()-new.keys()),
        compared_fields=daily_fields,differences=differences),
    noon=dict(observed=len(available),scored=sum(r.get('intraday_score') is not None for r in available),
        attack_scored=sum(r.get('live_attack_score') is not None for r in available),
        qualified_attack_rows=len(snap['attack_monitor']['rows']),live_candidates=snap['attack_monitor']['count'],
        risk_levels=dict(Counter(r['intraday_risk_level'] for r in available)),
        closed_price_differences=closing_differences),
    history=dict(prefix_unchanged=True,prefix_bytes=len(history_before),
        prefix_sha256=hashlib.sha256(history_before).hexdigest(),
        records_before=len(history_before.decode('utf-8').splitlines()),records_after=len(records),
        raw_input_records=len(raw),raw_record_counts=[len(r['rows']) for r in raw],
        raw_times=[r['captured_at'] for r in raw]),
    samples=[{k:r.get(k) for k in ('code','name','price','change_pct','stock_strength_score','trend_tier',
        'intraday_score','live_attack_score','live_attack_tier','live_attack_stage','intraday_judgment_at',
        'intraday_risk_flags','live_overheat_dist_atr','live_attack_fund','intraday_ma10_exact',
        'intraday_transition','intraday_path')} for r in allrows if r['code'] in ('000710','002962','603231')],
    event_samples=[dict(code=r['code'],name=r['name'],state=r['intraday_path']['state'],events=r['intraday_path']['events'])
                   for r in available if r['intraday_path']['events']][:8])
(OUT/'live_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result[k] for k in ('snapshot_at','daily_comparison','noon','history','event_samples')},ensure_ascii=False,indent=2))
