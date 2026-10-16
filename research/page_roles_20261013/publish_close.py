"""Recompute the live close snapshot using a real preserved closing batch."""
import gzip,json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import config,scoring,strength,market_strength as M,serve
root=Path(__file__).parent
s=json.loads((root/'live_close_before_fix.json').read_text('utf8'))
prior=json.loads((root/'validated_snapshot.json').read_text('utf8'))
with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions/2026-10-13.jsonl.gz','rt',encoding='utf8') as stream:
    acquisition=next(json.loads(line) for line in stream if json.loads(line)['captured_at']==s['quote_capture_at'])
quotes={str(row[0]):dict(zip(acquisition['fields'][1:],row[1:])) for row in acquisition['rows']}
pool=json.loads(Path('research/market_strength_v1_20261013/baseline/frozen_complete_inputs.json').read_text('utf8'))['pool']
histories=scoring.formal_histories(pool)
calendar=strength.trading_calendar({c:strength.completed(v) for c,v in histories.items()})
M.attach(s,quotes,pool,histories,calendar,now=datetime.fromisoformat(s['quote_capture_at']),previous=prior)
M.validate(s)
assert s['market_strength']['counts']['focus']>0
assert s['direction_changes']['source_at']=='2026-10-13 15:01:12'
assert s['market_strength_close_reference']['source_at']=='2026-10-13 15:01:12'
config.atomic_write_text(config.SNAPSHOT_JSON,json.dumps(s,ensure_ascii=False,separators=(',',':')))
serve.publish_outputs(s)
print(json.dumps(dict(counts=s['market_strength']['counts'],source=s['direction_changes']['source_at'],hash=M.IMPLEMENTATION_HASH),ensure_ascii=False))
