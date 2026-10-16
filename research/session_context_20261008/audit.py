"""只读检查完成日历史、价格来源及当前未知原因。"""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import datafeed as df
import intraday
import strength

def inspect():
    snap=json.loads((ROOT/'cache/snapshot.json').read_text(encoding='utf-8'))
    pool=json.loads((ROOT/'cache/pool.json').read_text(encoding='utf-8'))
    asof=snap['strength_model']['asof']
    conn=sqlite3.connect('file:'+str(ROOT/'cache/market.db')+'?mode=ro',uri=True)
    series={code:df.load_kline(conn,'kline','code',code) for code in pool}
    calendar=strength.trading_calendar({c:[b for b in bars if b['date']<=asof] for c,bars in series.items()})
    details=[];counts=Counter()
    known={('qfq',s) for s in intraday._QFQ_HISTORY_SOURCES}|{('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    for code,bars in series.items():
        completed=[b for b in bars if b['date']<=asof];tail=completed[-61:];issues=[]
        for n in (21,40,61):
            window=completed[-n:];expected=calendar[-n:]
            valid=(len(window)==n and [b['date'] for b in window]==expected and
                   all(intraday._valid_historical_price_bar(b) for b in window) and
                   len({(b.get('price_basis'),b.get('price_basis_source')) for b in window})==1 and
                   all((b.get('price_basis'),b.get('price_basis_source')) in known for b in window))
            counts['valid_'+str(n)]+=int(valid)
            if not valid:issues.append(str(n)+'日价格窗口缺口/来源未核验')
        if not all(intraday._positive(b.get('volume')) for b in completed[-20:]) or len(completed)<20:
            counts['volume20_issue']+=1;issues.append('20日有效成交量不足')
        if issues:details.append(dict(code=code,name=pool[code].get('name'),bars=len(completed),
                           latest=completed[-1]['date'] if completed else None,issues=issues))
    rows=snap['stocks']+snap.get('coverage_catalog',[])
    result=dict(snapshot_at=snap['generated_at'],daily_asof=asof,pool_count=len(pool),
                database_rows=conn.execute('SELECT COUNT(*) FROM kline').fetchone()[0],
                database_dates=conn.execute('SELECT MIN(date),MAX(date) FROM kline').fetchone(),
                windows=dict(counts),repair_candidates=details,
                basis_reasons=dict(Counter(r.get('intraday_price_basis_reason') or '可比' for r in rows)),
                fund_states=dict(Counter(r.get('fund_state') or '未知' for r in rows)),
                score_history_gaps={k:sum(r.get(k) is None for r in rows) for k in ('strength_delta1','strength_delta5')},
                daily_archive_dates=[p.stem for p in sorted((ROOT/'cache/stock_strength_daily/v6').glob('*.json'))],
                close_archive_dates=[p.stem for p in sorted((ROOT/'cache/close_strong_attack_v6').glob('*.json'))])
    return result

if __name__=='__main__':
    result=inspect()
    (Path(__file__).parent/'before.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='repair_candidates'},ensure_ascii=False))
