import copy,json,sys,shutil
from pathlib import Path
from unittest.mock import patch
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,board_quote,board_trend,make_dashboard,datafeed
HERE=Path(__file__).parent
snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
previous=copy.deepcopy(snap)
shutil.copy2(board_quote.CACHE,HERE/'quotes.json')
before=sum(bool((b.get('index_current') or {}).get('fetch_error')) for b in snap['board_catalog'])
with patch.object(board_quote,'CACHE',HERE/'quotes.json'):
    board_trend.attach(snap,fetch=False,quote_fetch=True,previous_snapshot=previous)
assert snap['stocks']==previous['stocks']
boards=[b for b in snap['board_catalog'] if b.get('index_current')]
errors=[dict(id=b['id'],quote=b['index_current'].get('quote_at'),error=b['index_current'].get('fetch_error'),reason=b['index_current'].get('reason')) for b in boards if b['index_current'].get('fetch_error') or not b['index_current'].get('ready')]
e=dict(version=board_quote.VERSION,before_errors=before,total=len(boards),ready=sum(b['index_current'].get('ready',False) for b in boards),errors=errors,times=dict(Counter(b['index_current'].get('quote_at') for b in boards)),source_health=datafeed.source_health_snapshot().get('ths_index_quotes'),stocks_unchanged=True)
snap['data_sources']['ths_index_quotes']=e['source_health']
(HERE/'evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
(HERE/'preview.json').write_text(json.dumps(snap,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
html=make_dashboard.TPL.read_text(encoding='utf-8').replace(make_dashboard.PLACEHOLDER,json.dumps(snap,ensure_ascii=False,separators=(',',':')))
config.atomic_write_text(HERE/'preview.html',html)
print(json.dumps(e,ensure_ascii=False))
assert len(boards)==450 and not errors
