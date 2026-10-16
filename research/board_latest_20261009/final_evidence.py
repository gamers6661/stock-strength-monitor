import json,sys
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config,board_trend,board_center

def get(path):
    with urlopen('http://127.0.0.1:8848'+path,timeout=15) as r:return r.read().decode('utf-8')
status=json.loads(get('/__status'))
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
served,_=json.JSONDecoder().raw_decode(get('/dashboard.html').split('var DATA = ',1)[1].lstrip())
assert status['phase']=='ready' and status['last_publish_ok']
assert status['code_board_trend_version']==status['snapshot_board_trend_version']==s['board_trend_model']['version']==served['board_trend_model']['version']==board_trend.VERSION
assert s['board_catalog']==served['board_catalog']
assert s['board_trend_model']==served['board_trend_model']
b=next(b for b in served['board_catalog'] if b['id']=='industry:电池')
c=b['index_current']
assert c['ready'] and c['mode']=='current' and c['quote_at'][:10]==s['board_trend_model']['captured_at'][:10]
assert c['code']=='881281' and c['name']=='电池'
for kind,names in board_center._catalog().items():
    assert names <= {b['name'] for b in served['board_catalog'] if b['type']==kind}
e=dict(pid=status['pid'],version=board_trend.VERSION,snapshot_at=s['generated_at'],quote_capture_at=s['quote_capture_at'],
       board_model=s['board_trend_model'],battery_daily=b['index_trend'],battery_current=c,
       battery_quote=b['index_quote'],battery_mainboard_member_count=b['valid_members'],membership_stale=b['membership_stale'],
       industry_cards=sum(b['type']=='industry' for b in s['board_catalog']),theme_cards=sum(b['type']=='theme' for b in s['board_catalog']),
       snapshot_and_http_match=True,refresh_seconds=config.RUNTIME['refresh_seconds'])
Path(__file__).with_name('live-evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(pid=e['pid'],version=e['version'],snapshot_at=e['snapshot_at'],quote_at=c['quote_at'],state=c['state'],price=c['close'],change=c['change_pct'],ma5=c['ma5'],ma10=c['ma10'],ma20=c['ma20'],ready=e['board_model']['current_ready'],pending=e['board_model']['current_pending']),ensure_ascii=False))
