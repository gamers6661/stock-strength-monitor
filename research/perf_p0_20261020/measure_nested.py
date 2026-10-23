"""Break down the two largest per-stock payloads."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import ui_payload


def size(value):
    return len(ui_payload.dumps(value).encode('utf-8'))


packet = json.loads(ui_payload.blob(ui_payload.active_generation(), 'summary'))
brief = ui_payload.unpack(packet)
rows = brief.get('stocks') or []

for field in ('ma_trend', 'session_context', 'market_strength', 'emotion_relay', 'trend_consolidation'):
    totals = {}
    present = 0
    for row in rows:
        model = row.get(field)
        if not isinstance(model, dict):
            continue
        present += 1
        for key, value in model.items():
            totals[key] = totals.get(key, 0) + size(value)
    print(f'\n{field}: present {present}, total {sum(totals.values())/1e6:.2f} MB')
    for key, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:20]:
        print(f'  {key:32s} {total/1e6:8.3f} MB')

activity = brief.get('stock_activity') or {}
print('\nstock_activity top keys:')
for key, value in sorted(activity.items(), key=lambda item: size(item[1]), reverse=True)[:20]:
    print(f'  {key:32s} {size(value)/1e6:8.3f} MB')
items = activity.get('items') or {}
if isinstance(items, dict):
    sample = list(items.values())[:1]
elif isinstance(items, list):
    sample = items[:1]
else:
    sample = []
if sample:
    print('activity item keys:')
    for key, value in sorted(sample[0].items(), key=lambda item: size(item[1]), reverse=True)[:25]:
        print(f'  {key:32s} {size(value)/1e6:8.3f} MB (sample)')
