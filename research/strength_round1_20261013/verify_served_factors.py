"""Check application HTTP data and exports; this is not browser visual acceptance."""
import csv
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config
import market_strength as M
import ui_payload

root = Path(__file__).parent
base = 'http://127.0.0.1:8848'
def get(path):
    return urlopen(base+path, timeout=30).read()
status = json.loads(get('/__status'))
token = status['ui_generation']
brief = ui_payload.unpack(json.loads(get('/__ui/summary?'+urlencode({'version':token}))))
saved = json.loads(config.SNAPSHOT_JSON.read_text('utf8'))
rows = {s['code']:s for s in saved['stocks']+saved.get('coverage_catalog',[])}
projected = {s['code']:s for s in brief['stocks']+brief.get('coverage_catalog',[])}
assert brief['market_strength'] == saved['market_strength']
assert 'emotion_observations' not in brief
for code, row in projected.items():
    assert row['market_strength'] == M.brief(rows[code]['market_strength'])
for axis in ('trend','emotion'):
    ids = brief['market_strength']['stocks'][axis]
    assert all(projected[c]['market_strength'][axis+'_score']>=65 for c in ids)
    ordered = brief['market_strength']['stocks']['sorts'][axis]
    scores = [projected[c]['market_strength'][axis+'_score'] for c in ordered]
    valid = [s for s in scores if s is not None]
    assert valid == sorted(valid, reverse=True)
codes = ['601811','001368','605287']
for code in codes:
    item = json.loads(get('/__ui/detail?'+urlencode({'version':token,'kind':'stock','id':code})))['item']
    assert item['market_strength']==rows[code]['market_strength']
    assert 'trend_selection' in item['market_strength']
    assert 'path' in item['market_strength']['emotion_parts']
data = json.dumps(dict(version=token,codes=codes,contexts={})).encode()
body = urlopen(Request(base+'/__ui/export',data=data,headers={'Content-Type':'application/json'}), timeout=90).read()
(root/'served_stock_sample.csv').write_bytes(body)
exported = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
assert [r['代码'] for r in exported]==codes
for r in exported:
    model=rows[r['代码']]['market_strength']
    assert float(r['趋势分'])==model['trend_score']
    assert float(r['情绪分'])==model['emotion_score']
    assert r['规则版本']==M.VERSION and r['实现哈希']==M.IMPLEMENTATION_HASH
    assert json.loads(r['完整模型依据'])==model
bid = brief['market_strength']['boards']['trend'][0]
board = json.loads(get('/__ui/detail?'+urlencode({'version':token,'kind':'board','id':bid})))['item']
board_data=json.dumps(dict(version=token,kind='board',ids=[bid])).encode()
board_csv=urlopen(Request(base+'/__ui/export',data=board_data,headers={'Content-Type':'application/json'}),timeout=30).read()
(root/'served_board_sample.csv').write_bytes(board_csv)
br=list(csv.DictReader(io.StringIO(board_csv.decode('utf-8-sig'))))[0]
assert json.loads(br['完整模型依据'])==board['market_strength']
out=dict(version=M.VERSION,pid=status['pid'],ui_generation=token,
         summary_rows=len(projected),counts=brief['market_strength']['counts'],
         sorted_axes_verified=['trend','emotion'],stock_detail_and_csv_verified=codes,
         board_detail_and_csv_verified=bid,internal_path_ring_hidden=True,
         browser_visual_acceptance='blocked by browser security policy; not completed')
(root/'served_factor_acceptance.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(out,ensure_ascii=False),flush=True)
