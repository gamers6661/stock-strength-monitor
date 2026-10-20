"""Freeze only chart display corrections; preserve every model and stock row."""
import hashlib,json,shutil,sys
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0,str(Path.cwd()))
import board_chart,config,ui_payload
root=Path(__file__).parent
status=json.load(urlopen('http://127.0.0.1:8848/__status',timeout=10));old=ui_payload.active_generation()
assert status['phase']=='ready' and not status['scan_active']
if not (root/'published.before.db').exists():shutil.copy2(ui_payload.db_path(old),root/'published.before.db')
source_hash=hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest()
full=ui_payload.full(old);original_boards=full['board_catalog']
template=ui_payload.blob(old,'template').decode('utf8')
old_script=(root/'board_chart_ui.js').read_text('utf8');new_script=(config.ROOT/'board_chart_ui.js').read_text('utf8')
if old_script in template:
    assert template.count(old_script)==1
    template=template.replace(old_script,new_script)
else:assert template.count(new_script)==1
result=board_chart.attach(full,refresh=True)
assert {k:v for k,v in full.items() if k not in ('board_catalog','board_chart_refresh')}=={k:v for k,v in result.items() if k not in ('board_catalog','board_chart_refresh')}
for a,b in zip(original_boards,result['board_catalog']):assert {k:v for k,v in a.items() if k!='index_chart'}=={k:v for k,v in b.items() if k!='index_chart'}
target=next(b for b in result['board_catalog'] if b['id']=='theme:租售同权')
assert target['index_chart']['asof']=='2026-10-16',target['index_chart']
packet,token=ui_payload.prepare(result,template,config.ROOT/'dashboard.html')
with config.pipeline_guard():
    assert ui_payload.active_generation()==old
    assert hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest()==source_hash
    config.atomic_write_text(config.ROOT/'dashboard.html',template.replace('/*__DATA__*/null',config.script_json(packet)))
    ui_payload.activate(token,config.ROOT/'dashboard.html')
evidence=dict(previous_generation=old,ui_generation=token,refresh=result['board_chart_refresh'],
    asof=target['index_chart']['asof'],last_bar=target['index_chart']['bars'][-1],
    scores_membership_and_stock_rows_unchanged=True,raw_snapshot_unchanged=True,
    current_ready=sum((b.get('index_chart') or {}).get('asof')=='2026-10-16' for b in result['board_catalog']),
    remaining=[dict(id=b['id'],reason=b['index_chart'].get('reason')) for b in result['board_catalog'] if (b.get('index_trend') or {}).get('code') and b['index_chart'].get('asof')!='2026-10-16'])
root.joinpath('publication.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(evidence,ensure_ascii=False,indent=2))
