import difflib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import ma_trend
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline'
parts=[]
for p in BASE.iterdir():
    current=ROOT/p.name
    if p.suffix not in ('.py','.js') or not current.exists():continue
    parts.extend(difflib.unified_diff(p.read_text(encoding='utf-8').splitlines(True),current.read_text(encoding='utf-8').splitlines(True),fromfile='before/'+p.name,tofile='after/'+p.name))
(OUT/'source.diff').write_text(''.join(parts),encoding='utf-8')
report=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf-8'))
assert report['hash']==ma_trend.IMPLEMENTATION_HASH
print('final hash',ma_trend.IMPLEMENTATION_HASH,'diff lines',len(''.join(parts).splitlines()),'candidates',[(r['code'],r['event']['date']) for r in report['candidates']])
