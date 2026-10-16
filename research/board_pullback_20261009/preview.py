import copy
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import board_trend
import make_dashboard

HERE = Path(__file__).parent
snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
before_stocks = copy.deepcopy(snap['stocks'])
before_members = {b['id']: {k: copy.deepcopy(b.get(k)) for k in
    ('members','lists','trend_rank','ranking_eligible','member_codes','trend_pct')}
    for b in snap['board_catalog']}
model = board_trend.attach(snap, fetch=False)
assert before_stocks == snap['stocks']
assert before_members == {b['id']: {k: b.get(k) for k in
    ('members','lists','trend_rank','ranking_eligible','member_codes','trend_pct')}
    for b in snap['board_catalog']}
counts = Counter()
examples = {}
for b in snap['board_catalog']:
    t = b.get('index_trend') or {}
    if t.get('ready') and b['ranking_eligible']:
        counts[t['state']] += 1
        examples.setdefault(t['state'], []).append({'name':b['name'], 'type':b['type'],
            'close':t['close'], 'ma5':t['ma5'], 'ma10':t['ma10'], 'ma20':t['ma20'],
            'start':t['episode_start'], 'first_break':t['first_ma10_break'],
            'fixed_atr':t['pullback_atr'], 'stage':t['stage']})
make_dashboard.attach_klines(snap)
html = (ROOT/'dashboard_template.html').read_text(encoding='utf-8').replace(
    make_dashboard.PLACEHOLDER, json.dumps(snap, ensure_ascii=False, separators=(',',':')))
config.atomic_write_text(HERE/'preview.html', html)
evidence = dict(snapshot_at=snap['generated_at'], model=model, counts=dict(counts),
                examples={k:v[:4] for k,v in examples.items()},
                stocks_unchanged=True, member_rules_and_ranks_unchanged=True,
                refresh_seconds=config.RUNTIME['refresh_seconds'])
config.atomic_write_text(HERE/'replay-evidence.json', json.dumps(evidence, ensure_ascii=False, indent=2))
print(json.dumps({k:v for k,v in evidence.items() if k not in ('model','examples')}, ensure_ascii=False))
print('日历长度',len(model['calendar']),'指数就绪',model['ready'],'待核验',model['pending'])
