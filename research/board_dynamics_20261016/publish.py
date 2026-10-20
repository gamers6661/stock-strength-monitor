"""Publish the board-only projection while proving the frozen payload is intact."""
import gzip
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0,str(Path.cwd()))
import board_dynamics
import config
import ui_payload

root=Path(__file__).parent
def status():return json.load(urlopen('http://127.0.0.1:8848/__status',timeout=10))

before=status();old=ui_payload.active_generation()
assert before['phase']=='ready' and not before['scan_active']
with sqlite3.connect(root/'published.before.db') as con:
    baseline=json.loads(gzip.decompress(con.execute("SELECT value FROM meta WHERE id='full.gz'").fetchone()[0]))
    old_template=con.execute("SELECT value FROM meta WHERE id='template'").fetchone()[0].decode('utf8')
# Refuse a competing model/data publication rather than clobbering it.
expected=json.loads((root/'publication.json').read_text('utf8'))['ui_generation'] if (root/'publication.json').exists() else json.loads((root/'status.before.json').read_text('utf8'))['ui_generation']
assert old==expected
template=old_template
assert '/*__BOARD_DYNAMICS_SCRIPT__*/' not in template
assert template.count('installLazyDetails();')==1
script=(config.ROOT/'board_dynamics_ui.js').read_text('utf8')
template=template.replace('installLazyDetails();',script+'\ninstallLazyDetails();')
source_hash=hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest()
started=time.perf_counter()
baseline['board_dynamics']=board_dynamics.build(baseline)
assert template.replace(script+'\n','',1)==old_template
packet,token=ui_payload.prepare(baseline,template,config.ROOT/'dashboard.html')
saved=ui_payload.full(token)
projected=baseline.pop('board_dynamics')
assert saved.pop('board_dynamics')==json.loads(json.dumps(projected))
assert saved==baseline,'A non-board payload value changed'
with config.pipeline_guard():
    assert ui_payload.active_generation()==old
    assert hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest()==source_hash
    assert not status()['scan_active']
    config.atomic_write_text(config.ROOT/'dashboard.html',template.replace('/*__DATA__*/null',config.script_json(packet)))
    ui_payload.activate(token,config.ROOT/'dashboard.html')
result=dict(previous_generation=old,ui_generation=token,projection_version=board_dynamics.VERSION,
    original_payload_identical=True,original_template_identical_except_board_script=True,
    raw_snapshot_unchanged=True,raw_snapshot_sha256=source_hash,
    source_at=projected['source_at'],counts=projected['counts'],seconds=round(time.perf_counter()-started,3))
root.joinpath('publication.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(result,ensure_ascii=False,indent=2))
