from pathlib import Path
import difflib
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
parts=[]
for name in ('ma_trend.py','market_strength.py','make_dashboard.py','config.py','radar_ui.js','ma_trend_ui.js','csv_export.js','dashboard_template.html','ui_client.js','ui_payload.py'):
    before=(OUT/'baseline'/name).read_text(encoding='utf-8').splitlines();after=(ROOT/name).read_text(encoding='utf-8').splitlines()
    parts.extend(difflib.unified_diff(before,after,fromfile='before/'+name,tofile='after/'+name,lineterm=''))
for name in ('stock_rank_ui.js','board_stock_rank.py'):
    parts.extend(difflib.unified_diff([], (ROOT/name).read_text(encoding='utf-8').splitlines(),fromfile='/dev/null',tofile='after/'+name,lineterm=''))
(OUT/'source.diff').write_text('\n'.join(parts),encoding='utf-8')
print('Source diff saved; legacy market scores are checked separately on frozen inputs.')
