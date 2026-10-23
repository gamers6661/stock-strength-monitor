"""Read-only measurement of the active UI generation."""
import gzip
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import ui_payload


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    seconds = time.perf_counter() - start
    print(f'{label}: {seconds:.3f}s')
    return value, seconds


def size(value):
    return len(ui_payload.dumps(value).encode('utf-8'))


token = ui_payload.active_generation()
print('token', token)
db = ui_payload.db_path(token)
print('db MB', round(db.stat().st_size / 1e6, 2))
with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as con:
    for key in ('full.gz', 'summary', 'summary.gz', 'page.gz', 'template'):
        row = con.execute('SELECT length(value) FROM meta WHERE id=?', (key,)).fetchone()
        print(f'meta {key} MB', round(row[0] / 1e6, 2) if row else None)
    print('detail rows', con.execute('SELECT kind,count(*),sum(length(value)) FROM detail GROUP BY kind').fetchall())

packet = json.loads(ui_payload.blob(token, 'summary'))
brief, _ = timed('unpack', lambda: ui_payload.unpack(packet))
text, _ = timed('dumps(summary)', lambda: ui_payload.dumps(brief))
print('summary MB', round(len(text.encode('utf-8')) / 1e6, 2))
packed_text, _ = timed('dumps(packet)', lambda: ui_payload.dumps(packet))
print('packet MB', round(len(packed_text.encode('utf-8')) / 1e6, 2))
again, _ = timed('pack(summary)', lambda: ui_payload.pack(brief))
print('pack roundtrip bytes', len(ui_payload.dumps(again)))

print('\nTop-level summary sizes (MB):')
for key, value in sorted(brief.items(), key=lambda item: size(item[1]), reverse=True):
    print(f'  {key:32s} {size(value) / 1e6:8.2f}')

for group in ('stocks', 'coverage_catalog'):
    rows = brief.get(group) or []
    if not rows:
        continue
    print(f'\n{group}: {len(rows)} rows, avg keys {sum(len(r) for r in rows) / len(rows):.1f}')
    totals = {}
    presence = {}
    for row in rows:
        for key, value in row.items():
            totals[key] = totals.get(key, 0) + size(value)
            presence[key] = presence.get(key, 0) + 1
    for key, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:24]:
        print(f'  {key:32s} {total / 1e6:8.2f} MB  present {presence[key]}')

boards = brief.get('board_catalog') or []
print(f'\nboard_catalog: {len(boards)} rows, total MB {size(boards) / 1e6:.2f}')
if boards:
    totals = {}
    for row in boards:
        for key, value in row.items():
            totals[key] = totals.get(key, 0) + size(value)
    for key, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:15]:
        print(f'  {key:32s} {total / 1e6:8.2f} MB')

snapshot = ROOT / 'cache' / 'snapshot.json'
if snapshot.is_file():
    raw, _ = timed('read snapshot bytes', lambda: snapshot.read_bytes())
    print('snapshot MB', round(len(raw) / 1e6, 2))
    timed('sha256(snapshot)', lambda: hashlib.sha256(raw).hexdigest())
    timed('gzip(snapshot)', lambda: gzip.compress(raw, compresslevel=1))
    full, _ = timed('json.loads(snapshot)', lambda: json.loads(raw))
    stocks = full.get('stocks') or []
    encoded, seconds = timed('encode_detail stocks', lambda: [ui_payload.encode_detail(row) for row in stocks])
    print('detail stocks MB', round(sum(map(len, encoded)) / 1e6, 2), 'per-row ms', round(seconds / len(stocks) * 1000, 2) if stocks else None)
    csvs, seconds = timed('csv_row+encode_detail stocks', lambda: [ui_payload.encode_detail(ui_payload.csv_row(row)) for row in stocks])
    print('csv stocks MB', round(sum(map(len, csvs)) / 1e6, 2))
    summary_result, seconds = timed('summary(full)', lambda: ui_payload.summary(full, 'measurement-token'))
    print('summary result MB', round(size(summary_result) / 1e6, 2))
    packed_result, seconds = timed('pack(summary(full))', lambda: ui_payload.pack(summary_result))
    print('packed summary MB', round(size(packed_result) / 1e6, 2))
