import json
import sys
from pathlib import Path

if len(sys.argv) > 1:
    sys.path.insert(0, str(Path.cwd()))
    import ui_payload
    snap = ui_payload.full(sys.argv[1])
else:
    snap = json.loads(Path('cache/snapshot.json').read_text(encoding='utf-8'))
rows = {r['code']: r for r in snap['stocks'] + snap.get('coverage_catalog', [])}
found = []
for period in (5, 10, 20):
    obs = snap.get(f'trend_ma{period}_observation', {})
    for item in obs.get('main_rows', []) + obs.get('reclaim_rows', []):
        row = rows[item['code']]
        if item['provisional_ma'] != row.get(f'intraday_ma{period}'):
            found.append({'code': item['code'], 'period': period, 'item': item,
                          'row': {k: v for k, v in row.items() if k.startswith('intraday_')
                                  or k in ('price', 'quote_at', 'last_close', 'ma_trend')}})
Path('research/ma_trend_rebuild_20261014/live_consistency_diagnosis.json').write_text(
    json.dumps(found, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'generated': snap.get('generated_at'), 'session': snap.get('session'), 'mismatches': len(found),
                  'first': [{ 'code': x['code'], 'period': x['period'], 'item_ma': x['item']['provisional_ma'],
                              'row_ma': x['row'].get(f"intraday_ma{x['period']}"),
                              'item_trigger': x['item'].get('threshold_price'),
                              'row_trigger': x['row'].get(f"intraday_ma{x['period']}_trigger_price")}
                            for x in found[:5]]}, ensure_ascii=False))
