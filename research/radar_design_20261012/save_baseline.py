import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config, json, shutil, hashlib, urllib.request, sqlite3
from datetime import datetime

out=ROOT/'research'/'radar_opportunity_v1_20261012'
before=out/'before'; before.mkdir(parents=True,exist_ok=False)
files=list(ROOT.glob('*.py'))+list(ROOT.glob('*.js'))+list(ROOT.glob('*.json'))+[ROOT/'dashboard_template.html']
for p in files:
    shutil.copy2(p,before/p.name)
for name in ['snapshot.json','pool.json','trend_consolidation','intraday_reference','session_context','ui_payloads/active.txt']:
    p=config.CACHE_DIR/name
    if p.exists():
        dest=before/'cache'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        if p.is_dir():shutil.copytree(p,dest)
        else:shutil.copy2(p,dest)
snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
shutil.copy2(config.SNAPSHOT_JSON,before/'frozen_snapshot.json')
with urllib.request.urlopen('http://127.0.0.1:8848/__status') as r: status=json.load(r)
(before/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
lists={tier:[r['code'] for r in snap['stocks'] if r.get('trend_tier')==tier] for tier in ['A','B','C']}
for key in ['attack_watch_candidate','startup_candidate','current_strong_candidate']:
    lists[key]=[r['code'] for r in snap['stocks'] if r.get(key)]
(before/'lists.json').write_text(json.dumps(lists,ensure_ascii=False,indent=2),encoding='utf-8')
# Exact recorded acquisition, not a fresh request. Preserve complete source archive and database.
day=snap['generated_at'][:10]
p=config.CACHE_DIR/'intraday_history'/'acquisitions'/(day+'.jsonl.gz')
if p.exists():shutil.copy2(p,before/p.name)
for p in config.CACHE_DIR.glob('*.db'):
    dest=before/p.name
    with sqlite3.connect(p) as src, sqlite3.connect(dest) as dst:src.backup(dst)
manifest={str(p.relative_to(before)):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in before.rglob('*') if p.is_file()}
(out/'baseline_manifest.json').write_text(json.dumps({'saved_at':str(datetime.now()),'data_version':status.get('data_version'),'generated_at':snap['generated_at'],'files':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'out':str(out),'sources':len(files),'data_version':status.get('data_version'),'lists':{k:len(v) for k,v in lists.items()}},ensure_ascii=False))
