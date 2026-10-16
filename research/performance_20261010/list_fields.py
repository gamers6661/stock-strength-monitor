"""Record a conservative list-field manifest; details/export remain complete."""
from pathlib import Path
import json
import re

root = Path(__file__).resolve().parents[2]
source = (root / 'dashboard_template.html').read_text(encoding='utf-8')
for name in ('showStock', 'showCoverageStock'):
    start = source.index('function ' + name + '(')
    end = source.find('\nfunction ', start + 10)
    source = source[:start] + source[end:]
keys = set(re.findall(r'\.([A-Za-z_][A-Za-z0-9_]*)', source))
keys.update(re.findall(r'["\x27]([A-Za-z_][A-Za-z0-9_]*)["\x27]', source))
(root / 'stock_list_fields.json').write_text(json.dumps(sorted(keys), indent=2), encoding='utf-8')
print(len(keys))
