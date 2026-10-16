from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import make_dashboard
import report
import ui_payload

HERE = Path(__file__).resolve().parent
fixture = HERE/'fixture'
config.CACHE_DIR = fixture/'cache'
config.KLINE_DB = config.CACHE_DIR/'market.db'
config.SNAPSHOT_JSON = config.CACHE_DIR/'snapshot.json'
make_dashboard.OUT = fixture/'dashboard.html'
snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
results = []
for i in range(2):
    data = deepcopy(snap)
    # Separate immutable generations without changing any judgment input/date.
    data['publication_probe'] = [time.time(), i]
    started = time.monotonic()
    make_dashboard.build(data)
    config.atomic_write_text(fixture/'report.md', report.build(data))
    results.append(round(time.monotonic()-started,3))

payload = {'formatter':(ROOT/'csv_export.js').read_text(encoding='utf-8'),
           'rows':data['stocks']+data['coverage_catalog'], 'data':data,'contexts':{}}
# CSV formatting is frozen/shared; ensure full rows and width stay available.
process = subprocess.run(['node',str(ROOT/'csv_runner.js')], input=json.dumps(payload,ensure_ascii=False),
                         text=True, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if process.returncode:
    raise RuntimeError(process.stderr)
import csv, io
rows = list(csv.reader(io.StringIO(process.stdout)))
checks = dict(seconds=results, csv_rows=len(rows)-1, csv_columns=len(rows[0]),
              csv_sha256=hashlib.sha256(process.stdout.encode('utf-8')).hexdigest(),
              generation=ui_payload.active_generation(fixture/'dashboard.html') if False else 'see fixture/cache/ui_payloads/active.txt',
              page_bytes=make_dashboard.OUT.stat().st_size)
(HERE/'publish_results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False))
assert checks['csv_rows']==3120 and checks['csv_columns']==228
