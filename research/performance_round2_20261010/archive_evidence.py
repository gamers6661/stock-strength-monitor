"""Archive owned test inputs and source diffs; no production cache writes."""
from pathlib import Path
import difflib
import json
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
diffs = []
for before in sorted(HERE.glob('*.before')):
    after = ROOT / before.name[:-7]
    if after.exists():
        diffs.extend(difflib.unified_diff(before.read_text(encoding='utf-8').splitlines(True),
                     after.read_text(encoding='utf-8').splitlines(True),
                     fromfile='before/'+after.name, tofile='after/'+after.name))
for name in ('scan_cache.py', 'history_increment.py', 'test_scan_performance.py'):
    diffs.extend(difflib.unified_diff([], (ROOT/name).read_text(encoding='utf-8').splitlines(True),
                 fromfile='/dev/null', tofile='after/'+name))
(HERE/'changes.diff').write_text(''.join(diffs), encoding='utf-8')
fixture = HERE/'fixture'
entries = []
with zipfile.ZipFile(HERE/'frozen_fixture.zip','w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
    for path in sorted(fixture.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(fixture)
        if 'ui_payloads' in rel.parts or path.name.startswith('scan_features.db') or path.name=='dashboard.html':
            continue
        archive.write(path, str(Path('fixture')/rel))
        entries.append(dict(path=str(rel), bytes=path.stat().st_size))
(HERE/'archive_manifest.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
print('archive bytes', (HERE/'frozen_fixture.zip').stat().st_size, 'files',len(entries))
