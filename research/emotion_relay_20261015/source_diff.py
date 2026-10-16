import difflib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
names=[p.name for p in (OUT/'baseline').glob('*') if p.suffix in ('.py','.js','.html')]
names+=['emotion_relay.py','relay_data.py','emotion_ui.js','test_emotion_relay.py','test_emotion_ui.py']
lines=[];changed=[]
for name in names:
    old=(OUT/'baseline'/name).read_text(encoding='utf-8') if (OUT/'baseline'/name).exists() else ''
    new=(ROOT/name).read_text(encoding='utf-8')
    if old!=new:
        changed.append(name);lines.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='baseline/'+name,tofile=name))
(OUT/'source.diff').write_text(''.join(lines),encoding='utf-8')
print(json.dumps(dict(changed=changed,ma_source_unchanged=(ROOT/'ma_trend.py').read_bytes()==(OUT/'baseline/ma_trend.py').read_bytes()),ensure_ascii=False))
