"""Compare real browser DOM/download evidence with the same published generation."""
import csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import ui_payload
root=Path(__file__).parent
observed=json.loads((root/'ui_observed.json').read_text('utf8'))
s=ui_payload.full(observed['generation'])
lists=s['market_strength']['stocks']
ranked=lambda axis:[c for c in lists['sorts'][axis] if c in set(lists[axis])]
assert observed['trend']==ranked('trend')[:100]
assert observed['emotion']==ranked('emotion')[:100]
assert observed['trend']!=observed['emotion']
boards={b['id']:set(b['member_codes']) for b in s['board_catalog']}
industry=boards['industry:出版'];theme=boards['theme:知识产权保护']
intersection=industry&theme
assert observed['industry']==[c for c in ranked('trend') if c in industry]
assert observed['intersection']==[c for c in ranked('trend') if c in intersection]
assert observed['union']==[c for c in ranked('trend') if c in industry|boards['industry:影视院线']]
assert set(observed['both'])==set(lists['both'])&intersection
assert set(observed['all'])==set(lists['all'])&intersection
with (root/'radar_export.csv').open(encoding='utf-8-sig',newline='') as stream:
    exported=list(csv.DictReader(stream))
assert [r['代码'] for r in exported]==observed['intersection']
assert all(r['UI版本']==observed['generation'] for r in exported)
rows={r['code']:r for r in s['stocks']+s['coverage_catalog']}
model=rows['601811']['market_strength']
assert '明显回落' in model['labels'] and '趋势推进' not in model['labels']
result=dict(generation=observed['generation'],counts=s['market_strength']['counts'],
    source_at=s['direction_changes']['source_at'],from_at=s['direction_changes']['from_at'],
    industry=len(observed['industry']),intersection=len(observed['intersection']),
    union=len(observed['union']),both=len(set(observed['both'])),all_members=len(set(observed['all'])),
    csv_rows=len(exported),trend_first=observed['trend'][0],emotion_first=observed['emotion'][0],
    implementation_hash=s['market_strength']['implementation_hash'],status='PASS')
(root/'ui_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(result,ensure_ascii=False))
