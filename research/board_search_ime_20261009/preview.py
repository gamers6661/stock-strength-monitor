import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,make_dashboard
source=ROOT/'research/member_complete_20261009/preview.json'
snap=json.loads(source.read_text(encoding='utf-8'))
html=make_dashboard.TPL.read_text(encoding='utf-8').replace(make_dashboard.PLACEHOLDER,json.dumps(snap,ensure_ascii=False,separators=(',',':')))
config.atomic_write_text(Path(__file__).with_name('preview.html'),html)
print('Preview generated from verified complete-member snapshot')
