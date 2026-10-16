"""最近20个完成日的参考重算；保留真实观察，参考不冒充当时的收盘记录。"""
from datetime import datetime
from collections import OrderedDict
import json

import config
import intraday
import stock_strength
import strength
import scan_cache

VERSION='完成日历史参考2'
_KEY_CACHE=OrderedDict()

def rule_signature():
    return scan_cache.signature(scan_cache.rules('history_reference.py','strength.py','stock_strength.py',
                                                'attack_model.py','intraday.py','config.py'))

def input_signatures(completed, calendar, days, rules):
    def calculate():
        result={}
        for day in calendar[-days:]:
            dates=[d for d in calendar if d<=day]
            bars={c:[b for b in ks if b['date']<=day] for c,ks in completed.items()}
            # The reference's existing calculations require at most the last 61 bars.
            # A rolling 160-bar acquisition window must not invalidate unchanged older references.
            result[day]=scan_cache.signature([rules,dates[-61:],
                {c:ks[-61:] for c,ks in bars.items() if usable(ks,dates)}])
        return result
    try:
        key=(str(config.CACHE_DIR),scan_cache.signature([rules,completed,calendar,days]))
    except (TypeError,ValueError):
        return calculate()
    if key not in _KEY_CACHE:
        _KEY_CACHE[key]=calculate()
        while len(_KEY_CACHE)>8:
            _KEY_CACHE.popitem(last=False)
    _KEY_CACHE.move_to_end(key)
    return dict(_KEY_CACHE[key])

def directory():
    return config.CACHE_DIR/'historical_reference_v6'

def usable(bars,calendar):
    if strength.core_window_issue(bars,calendar):return False
    modes={(b.get('price_basis'),b.get('price_basis_source')) for b in bars[-25:]}
    allowed={('qfq',s) for s in intraday._QFQ_HISTORY_SOURCES}|{('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    return len(modes)==1 and modes.issubset(allowed)

def ensure(series,asof,days=20):
    completed={c:[b for b in bars if b['date']<=asof] for c,bars in series.items()}
    calendar=strength.trading_calendar(completed)
    rules=rule_signature()
    signatures=input_signatures(completed,calendar,days,rules)
    generated=[]
    for day in calendar[-days:]:
        path=directory()/(day+'.json')
        existing=load(day)
        if existing and existing.get('input_signature')==signatures[day]:continue
        dates=[d for d in calendar if d<=day]
        bars={c:[b for b in ks if b['date']<=day] for c,ks in completed.items()}
        bars={c:ks for c,ks in bars.items() if usable(ks,dates)}
        metrics={c:strength.day_metrics(ks,dates) for c,ks in bars.items()}
        if not metrics:
            # Never keep a previously qualified reference after all current inputs fail validation.
            if path.exists():
                path.unlink()
            continue
        scored,count=stock_strength.score(metrics,{c:{} for c in metrics},bars)
        record=dict(version=stock_strength.VERSION,reference_version=VERSION,asof=day,
                    input_signature=signatures[day],rule_signature=rules,
                    reconstructed_at=datetime.now().isoformat(sep=' ',timespec='seconds'),
                    provenance='历史日线重算；使用当前股票池，不是当时实测名单',reference_count=count,
                    stocks={c:dict(percentile=r['stock_strength_percentile'],score=r['stock_strength_score'],
                                   close=bars[c][-1]['close'],tier=r['daily_attack_tier'],
                                   trend_online=bool(metrics[c]['trend_online']),atr20=metrics[c]['atr20'])
                            for c,r in scored.items()})
        directory().mkdir(parents=True,exist_ok=True)
        config.atomic_write_text(path,json.dumps(record,ensure_ascii=False,separators=(',',':')))
        generated.append(day)
    return dict(version=VERSION,asof=asof,available_days=[d for d in calendar[-days:] if load(d)],
                generated=generated,provenance='真实留档优先，缺失日期使用单独的历史重算参考')

def load(day):
    try:record=json.loads((directory()/(str(day)+'.json')).read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
    return record if (isinstance(record,dict) and record.get('version')==stock_strength.VERSION
                      and record.get('reference_version')==VERSION and record.get('asof')==day
                      and record.get('rule_signature')==rule_signature()) else {}
