"""Read real HTTP publication, detail, CSV and frozen offline contracts."""
import csv
import io
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import emotion_relay
import ma_trend
import scan_cache
import ui_payload

BASE = 'http://127.0.0.1:8848'
DIRECTORY = Path(__file__).parent


def get(path):
    with urlopen(BASE + path, timeout=120) as response:
        return response.read()


status = json.loads(get('/__status'))
assert status['phase'] == 'ready' and status['last_scan_ok'] and status['last_publish_ok'], status
assert status['code_scan_cache_version'] == scan_cache.VERSION
assert status['code_ma_trend_hash'] == ma_trend.IMPLEMENTATION_HASH
assert status['code_emotion_relay_hash'] == emotion_relay.IMPLEMENTATION_HASH
assert status['code_ui_payload_implementation_hash'] == ui_payload.IMPLEMENTATION_HASH
generation = status['ui_generation']
packet = json.loads(get('/__ui/summary?version=' + generation))
summary = ui_payload.unpack(packet)
assert summary['ui_generation'] == generation
detail = json.loads(get('/__ui/detail?version=' + generation + '&kind=stock&id=002668'))
assert detail['version'] == generation
assert detail['item']['chart_history'][-1]['date'] == summary['quote_capture_at'][:10]
request = Request(BASE + '/__ui/export', data=json.dumps(dict(kind='stock', version=generation,
                  codes=['002668'], contexts=dict(view='radar'))).encode('utf8'),
                  headers={'Content-Type': 'application/json'}, method='POST')
with urlopen(request, timeout=120) as response:
    exported = response.read().decode('utf-8-sig')
csv_rows = list(csv.DictReader(io.StringIO(exported)))
assert len(csv_rows) == 1 and csv_rows[0]['代码'] == '002668'
assert csv_rows[0]['UI版本'] == generation
offline_bytes = get('/__ui/offline?version=' + generation)
output = ROOT / 'output/playwright/audit-round2-offline.html'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(offline_bytes)
offline, _ = json.JSONDecoder().raw_decode(offline_bytes.decode('utf8').split('var DATA = ', 1)[1])
assert offline['ui_generation'] == generation
pinned = summary['stock_activity_snapshot']
assert offline['stock_activity']['result_version'] == pinned['result_version']
assert offline['stock_activity']['day'] == summary['quote_capture_at'][:10]
emotion_relay.validate(offline)
result = dict(pid=status['pid'], generation=generation, snapshot_at=summary['generated_at'],
              daily_asof=summary['strength_model']['asof'], code_hashes_match=True,
              chart_code='002668', chart_asof=detail['item']['chart_history'][-1]['date'],
              csv_rows=len(csv_rows), csv_version_match=True,
              frozen_activity_result=pinned['result_version'], frozen_activity_day=pinned['day'],
              offline_path=str(output), offline_bytes=len(offline_bytes), emotion_final_order_valid=True)
(DIRECTORY / 'live_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(result, ensure_ascii=False), flush=True)
