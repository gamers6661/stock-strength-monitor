"""真正的离线重建与 HTTP 离线导出均不能推进确认或日线记录。"""
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import make_dashboard
import board_opportunity
import board_trend
import ui_payload
HERE=Path(__file__).parent

def history_hashes():
    return {str(p.relative_to(config.CACHE_DIR)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (config.CACHE_DIR/'board_opportunity_daily').rglob('*.json')}

snapshot=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
history_before=history_hashes()
ops=[b['opportunity'] for b in snapshot['board_catalog']]
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'dashboard.html'
    with patch.object(make_dashboard,'OUT',path),patch.object(board_opportunity,'enrich',side_effect=AssertionError('离线不能重新计算机会')),patch.object(board_trend,'attach',side_effect=AssertionError('离线不能重评指数')):
        for _ in range(2):
            projected=copy.deepcopy(snapshot)
            make_dashboard.build(projected)
            assert [b['opportunity'] for b in projected['board_catalog']]==ops
            assert projected['board_opportunity_model']==snapshot['board_opportunity_model']
            assert history_before==history_hashes()
status=json.loads(urlopen('http://127.0.0.1:8848/__status').read())
token=status['ui_generation']
for _ in range(2):
    html=urlopen('http://127.0.0.1:8848/__ui/offline?version='+token).read().decode('utf-8')
    full,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip())
    assert full['board_opportunity_model']==ui_payload.full(token)['board_opportunity_model']
    assert history_before==history_hashes()
after=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
assert [b['opportunity'] for b in after['board_catalog']]==ops, '核验期间在线扫描更新了快照，需空闲时重跑'
evidence=dict(offline_builds=2,http_offline_exports=2,confirmation_unchanged=True,daily_files_unchanged=True,
              daily_record_files=history_before,generation=token,snapshot_at=snapshot['generated_at'])
(HERE/'offline_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
