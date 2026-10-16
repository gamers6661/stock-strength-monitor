import json,sys
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,board_center

def get(path):
 with urlopen('http://127.0.0.1:8848'+path,timeout=15) as r:return r.read().decode('utf-8')
st=json.loads(get('/__status'));s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
served,_=json.JSONDecoder().raw_decode(get('/dashboard.html').split('var DATA = ',1)[1].lstrip())
assert st['phase']=='ready' and st['last_publish_ok']
assert st['code_board_catalog_version']==st['snapshot_board_catalog_version']==s['board_catalog_version']==served['board_catalog_version']==board_center.VERSION
assert s['board_catalog']==served['board_catalog']
assert st['member_refresh']['interval_days']==served['member_refresh']['interval_days']==7
assert config.RUNTIME['refresh_seconds']==300
b=next(b for b in s['board_catalog'] if b['id']=='industry:电池')
assert b['membership_stale'] and not b['source_complete']
assert b['index_current']['ready']
e=dict(pid=st['pid'],version=board_center.VERSION,snapshot_at=s['generated_at'],policy=st['member_refresh'],refresh_seconds=300,
       battery_current=b['index_current'],member_source_complete=b['source_complete'],member_partial_preserved=b['membership_stale'],snapshot_and_page_match=True)
Path(__file__).with_name('live-evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(pid=e['pid'],version=e['version'],snapshot_at=e['snapshot_at'],policy=e['policy'],index_quote=b['index_current']['quote_at'],state=b['index_current']['state']),ensure_ascii=False))
