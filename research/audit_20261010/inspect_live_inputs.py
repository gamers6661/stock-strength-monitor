"""Read-only consistency scan of authoritative snapshot and SQLite inputs."""
from collections import Counter
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config
import strength

HERE=Path(__file__).resolve().parent
raw=config.SNAPSHOT_JSON.read_bytes()
snap=json.loads(raw)
rows=snap['stocks']+snap.get('coverage_catalog',[])
codes={r['code'] for r in rows}
asof=snap['strength_model']['asof']
calendar=None
series={c:[] for c in codes}
with closing(sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro',uri=True)) as con:
    quick_check=con.execute('PRAGMA quick_check').fetchall()
    source_counts=con.execute('SELECT price_basis,price_basis_source,COUNT(*) FROM kline GROUP BY price_basis,price_basis_source').fetchall()
    future=con.execute('SELECT code,date FROM kline WHERE date>? LIMIT 10',(datetime.now().date().isoformat(),)).fetchall()
    invalid=con.execute('SELECT COUNT(*) FROM kline WHERE open<=0 OR close<=0 OR high<low OR low>MIN(open,close) OR high<MAX(open,close) OR volume<0').fetchone()[0]
    names=('date','open','close','high','low','volume','amount','price_basis','price_basis_source')
    for row in con.execute('SELECT code,'+','.join(names)+' FROM kline ORDER BY code,date'):
        if row[0] in series and row[1]<=asof:
            series[row[0]].append(dict(zip(names,row[1:])))
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pending=[]
    if 'kline_fetch_state' in tables:
        for code,payload in con.execute('SELECT code,payload FROM kline_fetch_state'):
            try:
                if json.loads(payload).get('integrity_pending'):
                    pending.append(code)
            except (ValueError,TypeError,AttributeError):
                pending.append(code)
calendar=strength.trading_calendar(series)
core=Counter(strength.core_window_issue(bars,calendar) or 'valid' for bars in series.values())
duplicate_codes=[c for c,n in Counter(r['code'] for r in rows).items() if n>1]
duplicate_boards=[c for c,n in Counter(r['id'] for r in snap['board_catalog']).items() if n>1]
mixed=[c for c,bars in series.items() if bars and len({(b.get('price_basis'),b.get('price_basis_source')) for b in bars[-25:]})>1]
result=dict(asof=asof,snapshot_generated_at=snap['generated_at'],snapshot_sha256=hashlib.sha256(raw).hexdigest(),
    quoted_rows=len(rows),scored=len(snap['stocks']),boards=len(snap['board_catalog']),quick_check=quick_check,
    source_counts=source_counts,future_rows=future,invalid_ohlc_rows=invalid,duplicate_codes=duplicate_codes,
    duplicate_board_ids=duplicate_boards,core_windows=dict(core),mixed_recent_basis=mixed,
    pending_integrity=pending,real_close_count=len(snap['close_strong_board']['stocks']))
(HERE/'input_inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
assert quick_check==[('ok',)] and not future and invalid==0 and not duplicate_codes and not duplicate_boards
