import gzip
import json
import shutil
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
for name in ['make_dashboard.py', 'serve.py', 'dashboard_template.html',
             'check_dashboard.py', 'check_live_service.py']:
    if not (out / (name + '.before')).exists():
        shutil.copy2(root / name, out / (name + '.before'))
for name in ['dashboard.html', 'cache/snapshot.json']:
    if (out / (Path(name).name + '.before.gz')).exists():
        continue
    with (root / name).open('rb') as src, gzip.open(out / (Path(name).name + '.before.gz'), 'wb', compresslevel=1) as dst:
        shutil.copyfileobj(src, dst)
t = time.perf_counter()
snap = json.loads((root / 'cache/snapshot.json').read_text(encoding='utf-8'))
elapsed = time.perf_counter() - t
result = {'snapshot_bytes': (root / 'cache/snapshot.json').stat().st_size,
          'page_bytes': (root / 'dashboard.html').stat().st_size,
          'parse_seconds': elapsed, 'stocks': len(snap['stocks']) + len(snap.get('coverage_catalog', [])),
          'generated_at': snap['generated_at']}
if not (out / 'baseline.json').exists():
    (out / 'baseline.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(result)
