import csv,json,sys
from pathlib import Path
from urllib.request import urlopen
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT))
raw=(OUT/'browser_cli.txt').read_text(encoding='utf-8-sig')
result=json.loads(next(line for line in raw.splitlines() if line.startswith('{"base":')))
with (OUT/'browser_board_ranks.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
board=result['board'];assert [r['代码'] for r in rows]==board['expected']
for row in rows:
    item=board['items'][row['代码']]
    assert int(row['板块排名'])==item['rank']
    assert row['UI版本']==board['generation']
    assert row['参照板块']==board['name']
assert not result['errors']
(OUT/'browser_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
status=json.loads(urlopen('http://127.0.0.1:8848/__status').read())
assert status['code_ma_trend_hash']==status['snapshot_ma_trend_hash']==result['base']['hash']
assert status['code_market_strength_hash']==status['snapshot_market_strength_hash']
assert status['pid']>0 and status['phase']=='ready' and not status['needs_model_refresh']
(OUT/'status_after.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
summary=dict(generation=board['generation'],source=result['base']['source'],daily=result['base']['daily'],valid_quote_count=result['base']['validQuoteCount'],
    counts=result['base']['counts'],board=board['name'],members=len(rows),rendered_members=result['renderedMembers'],
    independent_emotion=result['independentEmotion'],tooltip_hover_and_focus=True,
    composition_stocks=result['composition'],composition_radar=result['radarComposition'],csv_same_generation_and_order=True,
    examples=[{k:r[k] for k in ('code','name','stage','status','reason','origin','last_confirmation','history_days','asof','source')} for r in result['examples']])
(OUT/'acceptance_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
