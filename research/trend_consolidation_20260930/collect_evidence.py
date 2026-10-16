from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
import trend_consolidation as tc

folder=Path(__file__).resolve().parent
with urlopen('http://127.0.0.1:8848/__status',timeout=15) as r: status=json.load(r)
assert status['phase']=='ready' and status['last_scan_ok'] is True
snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
with urlopen('http://127.0.0.1:8848/dashboard.html',timeout=15) as r: html=r.read().decode('utf-8')
served,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip())
model=snap['trend_consolidation']
assert model['version']==tc.VERSION==status['code_consolidation_version']==status['snapshot_consolidation_version']
assert model==served['trend_consolidation']
assert status['snapshot_generated_at']==snap['generated_at']==served['generated_at']
sources=['config.py','trend_consolidation.py','scoring.py','serve.py','intraday_path.py',
         'dashboard_template.html','test_trend_consolidation.py','check_live_service.py']
hashes={name:hashlib.sha256((config.ROOT/name).read_bytes()).hexdigest() for name in sources}
after=folder/'after';after.mkdir(exist_ok=True)
for name in sources: (after/name).write_bytes((config.ROOT/name).read_bytes())
with gzip.open(folder/'live_snapshot.json.gz','wt',encoding='utf-8') as stream: json.dump(snap,stream,ensure_ascii=False)
evidence=dict(status=status,generated_at=snap['generated_at'],model_version=model['version'],
              count=model['count'],current_count=model['current_count'],reference_count=model['reference_count'],
              stages=dict(Counter(r['stage'] for r in model['rows'])),
              shapes=dict(Counter(r['shape'] for r in model['rows'])),
              pending_count=model['pending_count'],withdrawn_count=len(model['withdrawn_rows']),
              daily_tiers=dict(Counter(r.get('daily_tier') for r in model['rows'])),
              source_sha256=hashes,rows=model['rows'])
(folder/'live_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in evidence.items() if k not in ('status','rows','source_sha256')},ensure_ascii=False))
