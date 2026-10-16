"""Replay the immutable real-market input; no market refresh and no source mutation."""
import copy,hashlib,json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import market_strength as M
O=Path(__file__).parent;B=Path('research/market_strength_v1_20261013/baseline')
raw=(B/'frozen_complete_inputs.json').read_bytes();f=json.loads(raw)
s=json.loads((B/'cache/snapshot.json').read_text('utf8'))
members=copy.deepcopy([b['member_codes'] for b in s['board_catalog']])
indices=copy.deepcopy([{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']])
M.attach(s,f['quotes'],f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(f['now']));M.validate(s)
assert members==[b['member_codes'] for b in s['board_catalog']]
assert indices==[{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']]
assert raw==(B/'frozen_complete_inputs.json').read_bytes()
old=json.loads((O/'baseline/frozen_v1_scores.json').read_text('utf8'))
rows={r['code']:r for r in s['stocks']+s['coverage_catalog']}
def stats(models,lists):
    def top(order):
        ids=lists['sorts'][order][:20]
        return dict(codes=ids,limits=sum(models[c].get('emotion_parts',{}).get('actual_limit',False) for c in ids),
                    negative_history20=sum((models[c].get('trend_parts_by_period',{}).get('20',{}).get('historical_R') or 0)<0 for c in ids))
    return {k:top(k) for k in ('trend','emotion','combined')}
old_models={c:r['new'] for c,r in old['stocks'].items()}
comparison=dict(input_hash=hashlib.sha256(raw).hexdigest(),now=f['now'],version=M.VERSION,
    before_counts=old['counts'],after_counts=s['market_strength']['counts'],board_before=old['board_counts'],board_after=s['market_strength']['board_counts'],
    after_radar_counts={k:len(s['market_strength']['stocks'][k]) for k in ('starting','pullback','day_attack')},
    after_top20=stats({c:r['market_strength'] for c,r in rows.items()},s['market_strength']['stocks']),
    stocks={c:dict(name=r['name'],before=old_models[c],after=r['market_strength']) for c,r in rows.items()},
    membership_unchanged=True,index_reference_unchanged=True,raw_input_unchanged=True)
(O/'comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),'utf8')
(O/'frozen_after.json').write_text(json.dumps(s,ensure_ascii=False,separators=(',',':')),'utf8')
print(json.dumps({k:v for k,v in comparison.items() if k!='stocks'},ensure_ascii=False,indent=2),flush=True)
