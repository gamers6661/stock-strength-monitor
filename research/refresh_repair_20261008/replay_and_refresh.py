"""重放13点原始输入；常驻服务空闲且收盘后才执行一次收盘数据修复。"""
import gzip
import json
from datetime import datetime
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import scoring
import make_dashboard
import config
import report

OUT = Path(__file__).parent
results = []
with gzip.open(ROOT / 'cache/intraday_history/acquisitions/2026-10-08.jsonl.gz', 'rt', encoding='utf-8') as stream:
    for line in stream:
        record = json.loads(line)
        if record['boundary'] != 'afternoon_open':
            continue
        fields = record['fields']
        quotes = {row[0]: dict(zip(fields[1:], row[1:])) for row in record['rows']}
        try:
            valid = scoring.opening_quotes_ready(quotes, datetime.fromisoformat(record['captured_at']), '午盘', 3023)
            result = dict(captured_at=record['captured_at'], accepted=True, valid_quotes=valid)
        except scoring.DataNotReady as error:
            result = dict(captured_at=record['captured_at'], accepted=False, error=str(error))
        results.append(result)
(OUT / 'replay.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(results, ensure_ascii=False), flush=True)

if '--refresh' in sys.argv:
    status = json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status', timeout=5))
    if status['scan_active'] or datetime.now().hour < 16:
        raise RuntimeError('常驻服务正在扫描或尚未收盘，不执行独立补取')
    scoring.run(mode='quick', boundary='close', progress=False)
    make_dashboard.build()
    config.atomic_write_text(ROOT / 'snapshot_report.md', report.build())
    print('本次收盘报价已补取并发布', flush=True)
