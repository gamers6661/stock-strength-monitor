"""Compare unchanged judgments and corrected chart projection on saved inputs."""
import copy
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import emotion_relay
import ui_payload
from test_emotion_relay import sample

directory = Path(__file__).parent
before = types.ModuleType('relay_before_audit')
before.__file__ = str(ROOT / 'emotion_relay.py')
exec(compile((directory / 'emotion_relay.py.before').read_text(encoding='utf8'), before.__file__, 'exec'), before.__dict__)
original = sample()
old, new = copy.deepcopy(original), copy.deepcopy(original)
for module, fixture in ((before, old), (emotion_relay, new)):
    s, q, p, h, cal, now, evidence = fixture
    module.attach(s, q, p, h, cal, now=now, evidence=evidence, persist=False, fetch=False)
assert [r['emotion_relay'] for r in old[0]['stocks']] == [r['emotion_relay'] for r in new[0]['stocks']]
emotion_relay.validate(new[0])
snapshot = json.loads((directory / 'snapshot.json').read_text(encoding='utf8'))
projected = ui_payload.chart_projection(snapshot)
rows = snapshot['stocks'] + snapshot.get('coverage_catalog', [])
updated = projected['stocks'] + projected.get('coverage_catalog', [])
display_fields = {'chart_history', 'chart_source', 'chart_at', 'chart_observation'}
assert [{k:v for k,v in r.items() if k not in display_fields} for r in rows] == [{k:v for k,v in r.items() if k not in display_fields} for r in updated]
day = snapshot['quote_capture_at'][:10]
sample_row = next(r for r in updated if r['code'] == '002668')
assert sample_row['chart_history'][-1]['date'] == day
result = dict(relay_stock_judgments_unchanged=True, chart_changes_are_display_only=True,
              frozen_generated_at=snapshot['generated_at'],
              charts_before=sum(bool(r.get('chart_history')) for r in rows),
              charts_after=sum(bool(r.get('chart_history')) for r in updated),
              sample=dict(code=sample_row['code'], date=sample_row['chart_history'][-1]['date']))
(directory / 'frozen_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(result, ensure_ascii=False))
