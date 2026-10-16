import collections,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import ui_payload
p=Path(__file__).parent
f=json.loads((p/'frozen_full.json').read_text('utf8'));s=ui_payload.summary(f,'frozen')
out={}
for group in ['stocks','board_catalog']:
    counts=collections.Counter()
    for r in s[group]:
        for k,v in r.items():counts[k]+=len(ui_payload.dumps(v).encode())
    out[group]=counts.most_common(22)
(p/'field_sizes.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(out,ensure_ascii=False),flush=True)
