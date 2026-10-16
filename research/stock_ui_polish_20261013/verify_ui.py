import csv
import json
from pathlib import Path
root=Path(__file__).parent
p=json.loads((root/'ui_observed.json').read_text('utf8'))
s=json.loads((root/'baseline/snapshot.json').read_text('utf8'))
lists=s['market_strength']['stocks']
assert p['ranks']==[str(i) for i in range(1,201)]
assert p['ids']==[c for c in lists['sorts']['trend'] if c in lists['trend']][:200]
assert not p['browseOpen']
assert p['.ms-direction-picker']['y']+p['.ms-direction-picker']['height']<=p['.ms-style-tabs']['y']
assert p['.ms-style-tabs']['y']+p['.ms-style-tabs']['height']<=p['.ms-toolbar']['y']
assert p['#ui-offline-button']['x']>p['#p-stocks h1']['x']+p['#p-stocks h1']['width']
board=next(b for b in s['board_catalog'] if b['name']=='出版' and b['type']=='industry')
rows=list(csv.DictReader((root/'filtered_export.csv').open(encoding='utf-8-sig',newline='')))
assert [r['代码'] for r in rows]==[c for c in lists['sorts']['emotion'] if c in lists['emotion'] and c in board['member_codes']]
result=dict(passed=True,rank_count=200,csv_rows=len(rows),direction_before_tabs=True,offline_upper_right=True,browse_collapsed=True)
(root/'ui_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
print(result)
