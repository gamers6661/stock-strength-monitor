import difflib,json,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT));import ma_trend
report=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf-8'))
assert report['hash']==ma_trend.IMPLEMENTATION_HASH
parts=[]
for p in (OUT/'baseline').iterdir():
    if p.suffix not in ('.py','.js','.html'):continue
    parts.extend(difflib.unified_diff(p.read_text(encoding='utf-8').splitlines(True),(ROOT/p.name).read_text(encoding='utf-8').splitlines(True),fromfile='before/'+p.name,tofile='after/'+p.name))
(OUT/'source.diff').write_text(''.join(parts),encoding='utf-8')
print('Final core and comparison agree:',ma_trend.IMPLEMENTATION_HASH)
