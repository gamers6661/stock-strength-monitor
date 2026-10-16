import gzip
import json
from collections import Counter
from pathlib import Path

path = Path('cache/intraday_history/acquisitions/2026-10-08.jsonl.gz')
with gzip.open(path, 'rt', encoding='utf-8') as stream:
    for line in stream:
        record = json.loads(line)
        captured = record['captured_at']
        if '13:00' <= captured[11:16] <= '13:04' or captured[11:16] >= '16:55':
            pos = record['fields'].index('quote_at')
            stamps = Counter(str(row[pos] or '')[:16] for row in record['rows'])
            print(json.dumps(dict(captured=captured, boundary=record['boundary'], rows=len(record['rows']), source_times=stamps.most_common(4)), ensure_ascii=False))
