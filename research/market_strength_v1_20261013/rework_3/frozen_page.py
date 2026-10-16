"""A labelled acceptance fixture; never activate or overwrite the live publication."""
import sys,json
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path.cwd()))
import market_strength as M,config,ui_payload
O=Path(__file__).parent;B=O.parent/'baseline';out=O/'frozen-browser';out.mkdir(exist_ok=True)
f=json.loads((B/'frozen_complete_inputs.json').read_text('utf8'));s=json.loads((B/'cache/snapshot.json').read_text('utf8'))
M.attach(s,f['quotes'],f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(f['now']));M.validate(s)
s.setdefault('runtime_contract',{}).update(code_market_strength_version=M.VERSION,code_market_strength_hash=M.IMPLEMENTATION_HASH)
template=(config.ROOT/'dashboard_template.html').read_text('utf8')
for marker,name in [('/*__RADAR_SCRIPT__*/','radar_ui.js'),('/*__CSV_SCRIPT__*/','csv_export.js'),('/*__UI_SCRIPT__*/','ui_client.js')]:template=template.replace(marker,(config.ROOT/name).read_text('utf8'))
template=template.replace('<body>','<body><div style="padding:12px;background:#fff0c2;color:#222">冻结输入验收 · 2026-10-13 11:31:11 · 非当前实盘发布</div>')
template=template.replace('installLazyDetails();','updateDashboardData=function(){return Promise.resolve();};installLazyDetails();')
packet,token=ui_payload.prepare(s,template,config.ROOT/'dashboard.html')
(O/'frozen_dashboard.html').write_text(template.replace('/*__DATA__*/null',config.script_json(packet)),'utf8')
by={r['code']:r for r in s['stocks']+s['coverage_catalog']};focus=s['market_strength']['stocks']['focus']
stock=ui_payload.export_csv(token,focus,{})
(out/'stocks.csv').write_bytes(stock)
for kind in ('industry','theme'):
    byboard={b['id']:b for b in s['board_catalog']};ids=[i for i in s['market_strength']['boards']['sorts']['combined'] if i in s['market_strength']['boards']['focus'] and byboard[i]['type']==kind]
    (out/(kind+'.csv')).write_bytes(ui_payload.export_board_csv(token,ids))
(O/'frozen_ui_verification.json').write_text(json.dumps(dict(generation=token,counts=s['market_strength']['counts'],board_counts=s['market_strength']['board_counts'],source_at=f['now'],current_publication_unchanged=True),ensure_ascii=False,indent=2),'utf8')
script=(O/'browser_check.js').read_text('utf8').replace("rework_3';","rework_3/frozen-browser';").replace('http://127.0.0.1:8848/dashboard.html','http://127.0.0.1:8848/research/market_strength_v1_20261013/rework_3/frozen_dashboard.html')
(O/'frozen_browser_check.js').write_text(script,'utf8')
print('Labelled frozen fixture, not activated:',token,s['market_strength']['counts'],flush=True)
