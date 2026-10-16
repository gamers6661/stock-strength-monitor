from pathlib import Path
from difflib import unified_diff
OUT=Path(__file__).parent;ROOT=OUT.parents[1]
files=['config.py','ma_trend.py','ma_trend_ui.js','stock_rank_ui.js','emotion_ui.js','csv_export.js',
       'test_ma_trend.py','test_latest_ma20.py','test_ma_radar_transition.py','test_wave_audit.py','test_ma20_dual.py']
chunks=[]
for name in files:
    original=OUT/'baseline'/name
    before=original.read_text(encoding='utf8').splitlines(keepends=True) if original.exists() else []
    after=(ROOT/name).read_text(encoding='utf8').splitlines(keepends=True)
    diff=list(unified_diff(before,after,fromfile='before/'+name,tofile='after/'+name))
    chunks+=diff
    print(name,'+',sum(line.startswith('+') and not line.startswith('+++') for line in diff),
          '-',sum(line.startswith('-') and not line.startswith('---') for line in diff))
(OUT/'implementation.patch').write_text(''.join(chunks),encoding='utf8')
