import importlib.util,json,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,market_strength as M,ui_payload
p=Path(__file__).parent
spec=importlib.util.spec_from_file_location('payload_before',p/'baseline/ui_payload.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
f=json.loads((p/'frozen_full.json').read_text('utf8'))
a=old.summary(f,'same-generation');b=ui_payload.summary(f,'same-generation')
assert M.IMPLEMENTATION_HASH==f['market_strength']['implementation_hash']
assert json.loads(json.dumps(config.MARKET_STRENGTH))==f['market_strength']['parameters']
assert a['market_strength']==b['market_strength']
for group in ['stocks','coverage_catalog']:
    for before,after in zip(a[group],b[group]):
        assert before['code']==after['code']
        assert before['market_strength']==after['market_strength']
        assert {k:v for k,v in before.items() if k!='radar_opportunity'}==after
for before,after in zip(a['board_catalog'],b['board_catalog']):
    assert before['member_codes']==after['member_codes']
    assert before['market_strength']==after['market_strength']
    assert before['lists']==after['lists']
    assert before['opportunity']==after['opportunity']
    assert [{k:v for k,v in r.items() if k!='market_strength'} for r in before['members']]==after['members']
for name in ['dashboard_template.html','ui_client.js','radar_ui.js','market_strength.py']:
    assert Path(name).read_bytes()==(p/'baseline'/name).read_bytes(),name
out=dict(stock_scores_and_lists_unchanged=True,board_scores_and_members_unchanged=True,
         rule_parameters_and_implementation_unchanged=True,layout_and_client_scripts_byte_unchanged=True,
         old_packet_bytes=len(ui_payload.dumps(old.pack(a)).encode()),
         new_packet_bytes=len(ui_payload.dumps(ui_payload.pack(b)).encode()))
(p/'frozen_projection_check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(out,ensure_ascii=False),flush=True)
