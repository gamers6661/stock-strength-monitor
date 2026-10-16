import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config
import board_center

def get(path):
    with urlopen('http://127.0.0.1:8848'+path,timeout=15) as r:return r.read().decode('utf-8')
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
status=json.loads(get('/__status'))
served,_=json.JSONDecoder().raw_decode(get('/dashboard.html').split('var DATA = ',1)[1].lstrip())
assert status['phase']=='ready' and status['last_publish_ok']
assert status['code_board_catalog_version']==status['snapshot_board_catalog_version']==s['board_catalog_version']==served['board_catalog_version']==board_center.VERSION
assert s['board_catalog']==served['board_catalog']
cat=board_center._catalog()
for kind,names in cat.items():assert names <= {b['name'] for b in served['board_catalog'] if b['type']==kind}
target=next(b for b in served['board_catalog'] if b['id']=='industry:种植业与林业')
assert target['valid_members']>=6 and target['index_trend']['ready']
assert target['index_trend']['asof']==served['strength_model']['asof']
mem=json.loads(config.THS_INDUSTRY_MEMBER_CACHE.read_text(encoding='utf-8'))
e=dict(pid=status['pid'],last_scan=status['last_scan'],snapshot_at=s['generated_at'],
    version=board_center.VERSION,official_industries=len(cat['industry']),
    official_themes=len(cat['theme']),industry_cards=sum(b['type']=='industry' for b in served['board_catalog']),
    theme_cards=sum(b['type']=='theme' for b in served['board_catalog']),
    missing_industries=[],missing_themes=[],snapshot_and_http_match=True,
    source_industries_with_members=len({n for ns in mem['map'].values() for n in ns}),
    membership_refresh_incomplete=len(mem['stat']['failed']),
    target={k:target[k] for k in ('id','valid_members','pool_members','member_codes','membership_stale')},
    target_index={k:target['index_trend'][k] for k in ('code','asof','state','close','ma5','ma10','ma20')},
    refresh_seconds=config.RUNTIME['refresh_seconds'])
Path(__file__).with_name('live-evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(e,ensure_ascii=False))
