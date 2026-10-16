"""Verify the actual local publication without fetching market data."""
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config
import market_strength as M
import ui_payload

root = Path(__file__).parent
s = json.loads(config.SNAPSHOT_JSON.read_text('utf8'))
M.validate(s)
status = json.loads(urlopen('http://127.0.0.1:8848/__status', timeout=15).read())
token = status['ui_generation']
summary = ui_payload.unpack(json.loads(ui_payload.blob(token, 'summary')))
full = ui_payload.full(token)
assert 'emotion_observations' not in summary
assert summary == ui_payload.summary(full, token)
assert full['market_strength'] == s['market_strength']
assert status['code_market_strength_hash'] == status['snapshot_market_strength_hash'] == M.IMPLEMENTATION_HASH
assert status['phase'] == 'ready' and not status['needs_model_refresh']
result = dict(version=M.VERSION, implementation_hash=M.IMPLEMENTATION_HASH,
              pid=status['pid'], ui_generation=token,
              source_at=s['direction_changes']['source_at'],
              counts=s['market_strength']['counts'],
              snapshot_sha256=hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest(),
              summary_verified=True)
(root/'publication.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
(root/'status_after.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), 'utf8')
print(json.dumps(result, ensure_ascii=False), flush=True)
