"""Publish the validated frozen close, keeping its actual market timestamps."""
import hashlib,json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import config,market_strength as M,serve,ui_payload
root=Path(__file__).parent
rules=json.loads((root/'frozen_rules.json').read_text('utf8'))
assert rules['implementation_hash']==M.IMPLEMENTATION_HASH
assert config.SNAPSHOT_JSON.read_bytes()==(root/'baseline/snapshot.json').read_bytes(), 'live input changed during review'
s=json.loads((root/'validated_snapshot.json').read_text('utf8'));M.validate(s)
s['market_strength']['recalculated_at']=str(datetime.now())
config.atomic_write_text(config.SNAPSHOT_JSON,json.dumps(s,ensure_ascii=False,separators=(',',':')))
serve.publish_outputs(s)
summary=ui_payload.unpack(json.loads(ui_payload.blob(ui_payload.active_generation(),'summary')))
assert 'emotion_observations' not in summary
out=dict(version=M.VERSION,implementation_hash=M.IMPLEMENTATION_HASH,ui_generation=ui_payload.active_generation(),
         source_at=s['direction_changes']['source_at'],counts=s['market_strength']['counts'],
         snapshot_sha256=hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest())
(root/'publication.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf8')
print(out,flush=True)
