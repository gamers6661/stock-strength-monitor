import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import config,serve,ui_payload
root=Path(__file__).parent
raw=config.SNAPSHOT_JSON.read_bytes()
s=json.loads(raw)
def models(s):
    return json.dumps([s['market_strength'],[r.get('market_strength') for r in s['stocks']+s.get('coverage_catalog',[])],[b.get('market_strength') for b in s['board_catalog']]],sort_keys=True,ensure_ascii=False)
before=models(s)
serve.publish_outputs(s)
assert models(s)==before
assert config.SNAPSHOT_JSON.read_bytes()==raw
result=dict(ui_generation=ui_payload.active_generation(),snapshot_sha256=hashlib.sha256(raw).hexdigest(),strength_unchanged=True,counts=s['market_strength']['counts'])
(root/'publication.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
print(result)
