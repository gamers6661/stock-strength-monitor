"""Read-only diagnostics; counterexamples are synthetic, never market observations."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import market_strength as M
from test_market_strength import fixture

snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
rows = snap['stocks'] + snap.get('coverage_catalog', [])
valid = [r for r in rows if r.get('market_strength', {}).get('emotion_score') is not None]
different = [r for r in valid if r.get('emotion_strong') is not None
             and bool(r['emotion_strong']) != r['market_strength']['emotion_strong']]
weak_hold = [r for r in valid if r['market_strength']['emotion_strong']
             and (r['market_strength'].get('emotion_parts', {}).get('H') or 0) < 35]
board_groups = defaultdict(list)
for b in snap.get('board_catalog', []):
    board_groups[tuple(sorted(b.get('member_codes', [])))].append(b['name'])

f = fixture()
s, q, p, h, cal, now = f
code = next(iter(q))
for i, bar in enumerate(h[code][-6:]):
    c = 100 * 1.03**i
    bar.update(open=c, close=c, high=c*1.005, low=c*.995)
last = h[code][-1]['close']
q[code].update(last_close=last, price=last*1.06, open=last*1.10,
               high=last*1.10, low=last*1.06, change_pct=6., limit_up=last*1.10)
M.attach(s, q, p, h, cal, now=now)
m = next(r['market_strength'] for r in s['stocks'] if r['code'] == code)

out = dict(snapshot_generated_at=snap['generated_at'], model_version=M.VERSION,
           model_hash=M.IMPLEMENTATION_HASH, counts=snap['market_strength']['counts'],
           coverage=snap['market_strength']['coverage'], emotion_valid=len(valid),
           legacy_emotion_disagreement=len(different),
           legacy_examples=[dict(code=r['code'], name=r.get('name'),
               old=r['emotion_strong'], new=r['market_strength']['emotion_strong'],
               new_score=r['market_strength']['emotion_score']) for r in different[:8]],
           strong_with_hold_below_35=[dict(code=r['code'],name=r.get('name'),
               score=r['market_strength']['emotion_score'],
               hold=r['market_strength']['emotion_parts']['H']) for r in weak_hold],
           identical_board_members=[v for k,v in board_groups.items() if k and len(v)>1],
           emotion_missing_reasons=Counter(reason for r in rows
               if r.get('market_strength',{}).get('emotion_score') is None
               for reason in r.get('market_strength',{}).get('data_reasons',[])),
           synthetic_gap_fade=dict(description='最近5个完成日每日涨3%；当日高开10%回落至涨6%，现价位于日内最低，过程抽样不足',
               emotion_score=m['emotion_score'], emotion_strong=m['emotion_strong'],
               hold=m['emotion_parts']['H'], position=m['emotion_parts']['L'],
               open_score=m['emotion_parts']['Oscore'], recent=m['recent_emotion']['score'],
               risks=m['risks'], labels=m['labels']))
Path(__file__).with_name('audit_evidence.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
