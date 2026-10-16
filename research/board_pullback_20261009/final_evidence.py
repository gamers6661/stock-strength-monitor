import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import board_trend

BASE = 'http://127.0.0.1:8848'
def read(path):
    with urlopen(BASE+path,timeout=15) as response:
        return response.read().decode('utf-8')

status = json.loads(read('/__status'))
snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
served, _ = json.JSONDecoder().raw_decode(read('/dashboard.html').split('var DATA = ',1)[1].lstrip())
assert status['phase'] == 'ready' and status['last_scan_ok'] and status['last_publish_ok']
assert status['code_board_trend_version'] == status['snapshot_board_trend_version'] == board_trend.VERSION
assert served['board_trend_model'] == snapshot['board_trend_model']
assert served['generated_at'] == snapshot['generated_at']
assert [b.get('index_trend') for b in served['board_catalog']] == [b.get('index_trend') for b in snapshot['board_catalog']]
counts = {}
keys = ('priority_observation','strong_advance','startup','pullback','support_observation','weak')
for kind in ('industry','theme'):
    rows = [b for b in served['board_catalog'] if b['type']==kind and b['ranking_eligible']]
    counts[kind] = {k:sum(bool((b.get('index_trend') or {}).get(k)) for b in rows) for k in keys}
advancing = []
for b in served['board_catalog']:
    t = b.get('index_trend') or {}
    if t.get('strong_advance') and b['ranking_eligible']:
        assert t['ma5'] > t['ma10']
        advancing.append(dict(name=b['name'],type=b['type'],**{k:t[k] for k in
            ('asof','close','ma5','ma10','ma20','ma5_prev','ma10_prev')}))
evidence = dict(pid=status['pid'], version=board_trend.VERSION,last_scan=status['last_scan'],
    snapshot_at=served['generated_at'], quote_capture_at=served['quote_capture_at'],
    daily_asof=served['board_trend_model']['asof'], index_ready=served['board_trend_model']['ready'],
    calendar_days=len(served['board_trend_model']['calendar']), counts=counts,
    advancing=advancing, snapshot_and_http_match=True,
    refresh_seconds=config.RUNTIME['refresh_seconds'])
Path(__file__).with_name('live-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in evidence.items() if k!='advancing'},ensure_ascii=False))
