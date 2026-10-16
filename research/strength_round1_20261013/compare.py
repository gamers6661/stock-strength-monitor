"""Same immutable input, both model contracts; no fetch or live publication."""
import copy,hashlib,json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import market_strength as M

root=Path(__file__).parent
raw=(root/'frozen_inputs.json').read_bytes();f=json.loads(raw)
rules=json.loads((root/'frozen_rules.json').read_text('utf8'))
assert rules['implementation_hash']==M.IMPLEMENTATION_HASH
assert rules['input_sha256']==hashlib.sha256(raw).hexdigest()
old=json.loads((root/'baseline/snapshot.json').read_text('utf8'))
before=json.loads((root/'baseline/recomputed.json').read_text('utf8'))
s=copy.deepcopy(old)
members=[b['member_codes'] for b in s['board_catalog']]
indices=[{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']]
raw_prices={r['code']:{k:r.get(k) for k in ['price','open','high','low','change_pct','limit_pct','amount_wan','turnover']} for r in s['stocks']+s['coverage_catalog']}
M.attach(s,f['quotes'],f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(f['now']),previous=old)
M.validate(s)
assert members==[b['member_codes'] for b in s['board_catalog']]
assert indices==[{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']]
assert raw_prices=={r['code']:{k:r.get(k) for k in ['price','open','high','low','change_pct','limit_pct','amount_wan','turnover']} for r in s['stocks']+s['coverage_catalog']}
assert (root/'frozen_inputs.json').read_bytes()==raw
for name,value in rules['ui_sha256'].items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==value
for name in ['dashboard_template.html','ui_client.js']:
    assert Path(name).read_bytes()==(root/'baseline'/name).read_bytes()
old_js=(root/'baseline/radar_ui.js').read_text('utf8').splitlines()
new_js=Path('radar_ui.js').read_text('utf8').splitlines()
assert len(old_js)==len(new_js)
changed=[(i+1,a,b) for i,(a,b) in enumerate(zip(old_js,new_js)) if a!=b]
assert [i for i,_,_ in changed]==[107,112,113]
assert all('强度计算依据与实际数值' in line for line in changed[0][1:])
# A concurrent candle-display task added chart_history and its source caption.
# Preserve those edits rather than restore an earlier chart implementation.
assert new_js[111]==old_js[111].replace('s.strength_history||[]','s.chart_history||s.strength_history||[]')
assert 'chart_source' in new_js[112]

def summarize(snapshot):
    rows={r['code']:r for r in snapshot['stocks']+snapshot['coverage_catalog']};meta=snapshot['market_strength']
    out=dict(counts=meta['counts'],board_counts=meta['board_counts'],top={},cases={})
    for axis in ['trend','emotion']:
        ids=[c for c in meta['stocks']['sorts'][axis] if rows[c]['market_strength'][axis+'_strong']][:20]
        out['top'][axis]=[dict(code=c,name=rows[c]['name'],score=rows[c]['market_strength'][axis+'_score'],change_pct=rows[c].get('change_pct')) for c in ids]
    for c in ['601811','001368','605287']:
        m=rows[c]['market_strength'];out['cases'][c]=dict(name=rows[c]['name'],trend=m['trend_score'],emotion=m['emotion_score'],rank=meta['stocks']['sorts']['trend'].index(c)+1,phase=m['phase'],selection=m.get('trend_selection'))
    out['path_available']=sum(bool(r['market_strength'].get('emotion_parts',{}).get('path',{}).get('available')) for r in rows.values())
    out['pullback_count']=len(meta['stocks']['pullback'])
    return out

result=dict(version=M.VERSION,input_sha256=rules['input_sha256'],before=summarize(before),after=summarize(s),
            raw_input_unchanged=True,prices_unchanged=True,membership_unchanged=True,index_unchanged=True,ui_layout_unchanged=True,ui_formula_text_only=True,concurrent_chart_change_preserved=True,
            stocks={r['code']:r['market_strength'] for r in s['stocks']+s['coverage_catalog']})
(root/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
(root/'validated_snapshot.json').write_text(json.dumps(s,ensure_ascii=False,separators=(',',':')),'utf8')
print(json.dumps({k:v for k,v in result.items() if k!='stocks'},ensure_ascii=False,indent=2),flush=True)
