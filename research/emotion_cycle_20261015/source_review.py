import difflib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline'
names=['config.py','emotion_relay.py','relay_data.py','relay_history.py','relay_regulation.py','relay_cycles.py','emotion_ui.js','csv_export.js','dashboard_template.html','ui_payload.py','serve.py','make_dashboard.py','scoring.py','stock_rank_ui.js','ma_trend.py','ma_trend_ui.js','board_stock_rank.py']
diff=[];changed=[]
for name in names:
 old=(BASE/name).read_text(encoding='utf-8') if (BASE/name).exists() else ''
 new=(ROOT/name).read_text(encoding='utf-8')
 if old!=new:
  changed.append(name);diff.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='before/'+name,tofile='after/'+name))
for name in ['ma_trend.py','ma_trend_ui.js','board_stock_rank.py','relay_data.py','ui_payload.py','serve.py','make_dashboard.py','scoring.py']:
 assert (BASE/name).read_bytes()==(ROOT/name).read_bytes(),name
(OUT/'source.diff').write_text(''.join(diff),encoding='utf-8')
(OUT/'source_review.json').write_text(json.dumps(dict(changed=changed,ma_and_original_integrations_unchanged=True),ensure_ascii=False,indent=2),encoding='utf-8')
print(changed)
