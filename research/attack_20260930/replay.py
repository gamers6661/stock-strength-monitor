"""同一冻结输入新旧对照；不写线上快照、缓存或历史。"""
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
import attack_model
import config
import intraday
import radar
import stock_strength
import strength

OUT = Path(__file__).parent


def run():
    old = json.loads((OUT/'frozen_snapshot.json').read_text(encoding='utf-8'))
    asof = old['strength_model']['asof']
    frozen = OUT/'frozen_klines.json.gz'
    if not frozen.exists():
        pool = json.loads(config.POOL_CACHE.read_text(encoding='utf-8'))
        series = {}
        keys = ('date','open','close','high','low','volume','amount','price_basis','price_basis_source')
        with sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro', uri=True) as conn:
            query = '''SELECT code,date,open,close,high,low,volume,amount,price_basis,price_basis_source
                       FROM kline WHERE date<=? AND date>=? ORDER BY code,date'''
            for r in conn.execute(query, (asof, '2026-06-01')):
                if r[0] in pool:
                    series.setdefault(r[0], []).append(dict(zip(keys, r[1:])))
        with gzip.open(frozen,'wt',encoding='utf-8') as stream:
            json.dump(series, stream, ensure_ascii=False)
    with gzip.open(frozen,'rt',encoding='utf-8') as stream:
        series = json.load(stream)
    now = datetime.fromisoformat(old['quote_capture_at'])
    industries = {r['code']: r.get('primary_industry') for r in old['stocks']}
    rows, meta = strength.build(copy.deepcopy(old['stocks']), series, industries, now=now)
    outside = copy.deepcopy(old.get('coverage_catalog') or [])
    quotes = {r['code']: dict(r) for r in old['stocks']+outside}
    # 快照不保留原始报价协议字段；按它已经核验并记录的来源恢复解析契约。
    # 数值及时间不变，不能把来源未记录的旧行补成可比；线上验收另查真实报价链路。
    for q in quotes.values():
        source = q.get('intraday_price_basis_quote_source')
        if source in intraday._RAW_QUOTE_SOURCES:
            q.update(price_basis='raw', price_basis_source=source,
                     last_close_semantics='previous_trade_day_raw_close',
                     last_close_precision_digits=2)
    # 覆盖行没有正式强度；旧版结论不会冒充新版日线。
    for r in outside:
        for k in ('stock_strength_score','stock_strength_parts','stock_strength_percentile',
                  'daily_attack_tier','persistent_strong'):
            r.pop(k, None)
    with patch.object(intraday,'_latest_record',return_value=None), patch.object(intraday,'_latest_record_before',return_value=None):
        live_meta = intraday.enrich(rows, outside, quotes, series, list(quotes), captured_at=now,
                                  session=old['session'], save_reference=False,
                                  trading_calendar=strength.trading_calendar(series))
    contexts = live_meta.pop('_price_contexts')
    radar.assign_trend_tiers(rows)
    snap = {'session': old['session'], 'stocks': rows, 'coverage_catalog': outside,
            'strength_model': meta, 'intraday_model': live_meta}
    attack_model.enrich(snap, quotes, contexts)
    old_by = {r['code']: r for r in old['stocks']}
    by = {r['code']: r for r in rows}
    fields = ('code','name','stock_strength_score','stock_strength_percentile','trend_tier',
              'ret5','ret10','ret20','daily_attack_stage','live_attack_score','live_attack_tier',
              'live_attack_stage','attack_watch_candidate','intraday_risk_flags','intraday_price_basis_status')
    samples = []
    for code in ('000710','002962','603231'):
        samples.append({'old': {k:old_by[code].get(k) for k in fields},
                        'new': {k:by[code].get(k) for k in fields}})
    old_online = {c for c,r in old_by.items() if r.get('trend_online')}
    new_online = {c for c,r in by.items() if r.get('trend_online')}
    result = {'input_generated_at': old['generated_at'], 'input_quote_at': old['quote_capture_at'],
              'asof': asof, 'model': stock_strength.VERSION, 'parameters': attack_model.PARAMETERS,
              'quote_metadata_restore': '按旧快照已核验来源恢复解析契约，价格/时间不变；非原始报价报文，线上链路另验收',
              'old_rows':len(old_by), 'new_rows':len(rows),
              'reference_count':meta['strength_reference_count'],
              'trend_online_same':old_online==new_online,
              'unchanged_daily_metrics': all(all(by[c].get(k)==r.get(k) for k in
                    ('ret5','ret20','ma5','ma10','ma20','signal_close','signal_date','trend_online'))
                    for c,r in old_by.items() if c in by),
              'old_tiers':{k:sum(r.get('trend_tier')==k for r in old_by.values()) for k in 'ABC'},
              'new_tiers':{k:sum(r.get('trend_tier')==k for r in rows) for k in 'ABC'},
              'attack_monitor_count':snap['attack_monitor']['count'],
              'slow_a_count':sum(r.get('trend_tier')=='A' and r['ret5']<3 and r['ret10']<5 and r['ret20']<8 for r in rows),
              'samples':samples}
    (OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2), flush=True)
    assert result['trend_online_same'] and result['unchanged_daily_metrics']
    assert result['slow_a_count']==0
    assert by['000710']['live_attack_stage']=='反包修复'
    assert by['002962']['live_attack_event'] in ('整理突破','20日新高突破')
    assert by['603231']['trend_tier']!='A' and not by['603231']['attack_watch_candidate']
    for r in rows+outside:
        if not r.get('intraday_quote_fresh') or r.get('intraday_price_basis_comparable') is not True:
            assert not r.get('attack_watch_candidate')
    (OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'frozen_new_rows.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':
    run()
