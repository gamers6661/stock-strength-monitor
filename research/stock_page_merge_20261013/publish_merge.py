"""Publish the merged UI against unchanged backend strength results."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import config
import serve
import ui_payload

root = Path(__file__).parent
baseline = json.loads((root / 'baseline/snapshot.json').read_text('utf8'))
snapshot = json.loads(config.SNAPSHOT_JSON.read_text('utf8'))

def strength_state(s):
    return {
        'model': s['market_strength'],
        'stocks': {r['code']: r.get('market_strength') for r in s['stocks'] + s.get('coverage_catalog', [])},
        'boards': {r['id']: r.get('market_strength') for r in s.get('board_catalog', [])},
    }

before = strength_state(baseline)
assert strength_state(snapshot) == before, 'Snapshot changed before UI publication'
serve.publish_outputs(snapshot)
assert strength_state(snapshot) == before, 'UI publication changed strength results'
result = {
    'ui_generation': ui_payload.active_generation(),
    'model_hash': snapshot['market_strength']['implementation_hash'],
    'counts': snapshot['market_strength']['counts'],
    'strength_results_unchanged': True,
    'snapshot_sha256': hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest(),
    'baseline_snapshot_sha256': hashlib.sha256((root / 'baseline/snapshot.json').read_bytes()).hexdigest(),
}
(root / 'publication.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
print(json.dumps(result, ensure_ascii=False))
