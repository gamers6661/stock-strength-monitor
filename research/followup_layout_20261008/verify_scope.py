"""核对本轮仅变更展示及对应页面验收约定。"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
before = json.loads((OUT / 'backend_before.json').read_text(encoding='utf-8-sig'))
changed_files = []
for item in before:
    path = Path(item['Path'])
    if hashlib.sha256(path.read_bytes()).hexdigest().upper() != item['Hash']:
        changed_files.append(path.name)
assert set(changed_files) == {'check_dashboard.py', 'check_live_service.py'}, changed_files
frozen = json.loads((OUT / 'snapshot_before.json').read_text(encoding='utf-8-sig'))
assert hashlib.sha256(Path(frozen['Path']).read_bytes()).hexdigest().upper() == frozen['Hash'], '数据快照改变'

def functions(text):
    matches = list(re.finditer(r'^function (\w+)\([^\n]*', text, re.M))
    out = {}
    for i, match in enumerate(matches):
        piece = text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        piece = piece[:piece.rfind('\n}') + 2]
        out[match.group(1)] = piece.strip()
    return out

old = functions((OUT / 'dashboard_template.before.html').read_text(encoding='utf-8'))
new = functions((ROOT / 'dashboard_template.html').read_text(encoding='utf-8'))
changed = [name for name in old if old[name] != new.get(name)]
allowed = {'renderConsolidationMonitor', 'renderWorkboard', 'setWorkMode',
           'sessionContextDetail', 'renderStocks', 'setTrendLine'}
assert set(changed) <= allowed, changed
added = [name for name in new if name not in old]
assert set(added) == {'uiTrendPullbackItems', 'uiTrendPullbackTags', 'uiFollowupCard'}, added
result = dict(model_and_runtime_files_unchanged=len(before) - len(changed_files),
              changed_acceptance_checks=changed_files, snapshot_unchanged=True,
              changed_display_functions=changed, added_display_helpers=added,
              unchanged_functions=len(old) - len(changed))
(OUT / 'scope.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
