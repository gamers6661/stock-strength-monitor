"""冻结上午输入，重放价格口径、MA5风险与资金评分；不写生产数据。"""
import copy
from datetime import datetime
import gzip
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import intraday
import strength
import attack_model

OUT = Path(__file__).parent
old = json.loads(gzip.open(OUT/'frozen_snapshot.json.gz', 'rt', encoding='utf-8').read())
snap = copy.deepcopy(old)
rows = snap['stocks'] + snap.get('coverage_catalog', [])
quotes = {r['code']: copy.deepcopy(r) for r in rows}
series = {}
asof = old['strength_model']['asof']
frozen = OUT/'frozen_klines.json.gz'
if frozen.exists():
    series = json.loads(gzip.open(frozen, 'rt', encoding='utf-8').read())
else:
    keys = ('date','open','close','high','low','volume','amount','price_basis','price_basis_source')
    with sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro', uri=True) as conn:
        for record in conn.execute('SELECT code,date,open,close,high,low,volume,amount,price_basis,price_basis_source FROM kline WHERE date<=? AND date>=? ORDER BY code,date', (asof, '2026-06-01')):
            if record[0] in quotes:
                series.setdefault(record[0], []).append(dict(zip(keys, record[1:])))
    with gzip.open(frozen, 'wt', encoding='utf-8') as stream:
        json.dump(series, stream, ensure_ascii=False)
for q in quotes.values():
    source = q.get('intraday_price_basis_quote_source')
    if source in intraday._RAW_QUOTE_SOURCES:
        q.update(price_basis='raw', price_basis_source=source,
                 last_close_semantics='previous_trade_day_raw_close', last_close_precision_digits=2)
now = datetime.fromisoformat(old['quote_capture_at'])
with patch.object(intraday, '_latest_record', return_value=None), patch.object(intraday, '_latest_record_before', return_value=None):
    meta = intraday.enrich(snap['stocks'], snap.get('coverage_catalog', []), quotes, series, list(quotes),
        captured_at=now, session=old['session'], save_reference=False,
        trading_calendar=strength.trading_calendar(series))
contexts = meta.pop('_price_contexts')
attack_model.enrich(snap, quotes, contexts)
before = {r['code']:r for r in old['stocks']+old.get('coverage_catalog', [])}
by = {r['code']:r for r in rows}
daily_keys = ('stock_strength_score','stock_strength_parts','stock_strength_percentile','trend_tier','daily_attack_tier','trend_online','signal_date')
assert all(all(r.get(k)==before[c].get(k) for k in daily_keys) for c,r in by.items())
valid = [r for r in rows if r['live_attack_price_score'] is not None]
for r in valid:
    fund = r['live_attack_fund']
    expected = round(r['live_attack_price_score']*(1-fund['weight']) + fund['score']*fund['weight'], 2) if fund['score'] is not None else r['live_attack_price_score']
    assert r['live_attack_score'] == expected
    assert r['live_attack_tier'] != 'A' or r['live_attack_price_tier'] == 'A'
    if r.get('overheated') is not None:
        assert r['overheated'] == ((r['price']-r['intraday_ma5_exact'])/r['intraday_atr20'] > 3.5)
fields = ('code','name','live_attack_price_score','live_attack_price_tier','live_attack_score','live_attack_tier','live_attack_stage','live_attack_fund','attack_watch_candidate','live_overheat_dist_atr','overheated','intraday_risk_flags')
result = dict(input_at=old['generated_at'], session=old['session'], samples=len(rows), price_valid=len(valid),
    fund_valid=sum(r['live_attack_fund']['score'] is not None for r in valid),
    daily_zero_difference=True, old_monitor_count=old['attack_monitor']['count'], new_monitor_count=snap['attack_monitor']['count'],
    old_overheated=sum(r.get('overheated') is True for r in before.values()), new_overheated=sum(r.get('overheated') is True for r in rows),
    heat_removed=sum(before[c].get('overheated') is True and r.get('overheated') is False for c,r in by.items()),
    samples_detail=[{k:by[c].get(k) for k in fields} for c in ('000710','002962','603231')],
    method='按冻结快照已记录来源恢复报价契约；冻结行情/资金/日线全池回放，不改报价时间；非线上午休新信号')
(OUT/'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'replayed_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
