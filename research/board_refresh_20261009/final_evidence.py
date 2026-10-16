import json,sys
from pathlib import Path
from urllib.request import urlopen
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,board_quote
def get(path):
    with urlopen('http://127.0.0.1:8848'+path,timeout=20) as r:return r.read().decode('utf-8')
status=json.loads(get('/__status'))
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
served,_=json.JSONDecoder().raw_decode(get('/dashboard.html').split('var DATA = ',1)[1].lstrip())
assert status['phase']=='ready' and status['last_scan_ok'] and status['last_publish_ok']
assert status['code_board_quote_version']==board_quote.VERSION
assert json.loads(board_quote.CACHE.read_text(encoding='utf-8'))['fetch_version']==board_quote.VERSION
assert s['generated_at']==served['generated_at']
assert s['data_sources']['ths_index_quotes']==served['data_sources']['ths_index_quotes']
assert s['data_sources']['ths_index_quotes']['coverage']=='450/450'
assert s['data_sources']['ths_index_quotes']['status']=='ok'
boards=[b for b in served['board_catalog'] if b.get('index_current')]
assert len(boards)==450
now=datetime.now();session=s['board_trend_model']['phase']
for b in boards:
    q=b['index_current']
    assert q['ready'] and not q.get('fetch_error'),b['id']
    assert board_quote.freshness(q,now,session) is None,b['id']
    assert q['code']==b['index_trend']['code'] and q['name']==b['name']
assert config.RUNTIME['refresh_seconds']==300 and status['member_refresh']['interval_days']==7
e=dict(pid=status['pid'],version=board_quote.VERSION,snapshot=s['generated_at'],total=450,ready=450,errors=0,
       earliest_quote=min(b['index_current']['quote_at'] for b in boards),latest_quote=max(b['index_current']['quote_at'] for b in boards),
       source_health=s['data_sources']['ths_index_quotes'],refresh_seconds=300,weekly_days=7,snapshot_and_page_verified=True)
Path(__file__).with_name('live-evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(e,ensure_ascii=False))
