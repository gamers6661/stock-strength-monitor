# -*- coding: utf-8 -*-
import copy,difflib,hashlib,json,re,sys
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
import config,make_dashboard,board_opportunity,ui_payload

def hashes():return {p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (config.CACHE_DIR/'board_opportunity_daily').rglob('*.json')}
snapshot=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
before=hashes();copy_snapshot=copy.deepcopy(snapshot)
with patch.object(board_opportunity,'enrich',side_effect=AssertionError('页面返工不能重新计算机会')):
    make_dashboard.build(copy_snapshot)
assert copy_snapshot['board_opportunity_model']==snapshot['board_opportunity_model']
assert [b['opportunity'] for b in copy_snapshot['board_catalog']]==[b['opportunity'] for b in snapshot['board_catalog']]
assert hashes()==before
disk=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
assert disk==snapshot,'发布期间后台另有扫描，需要重跑以核对一致性'
html=urlopen('http://127.0.0.1:8848/dashboard.html').read().decode('utf-8')
packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip());brief=ui_payload.unpack(packet)
assert brief['board_opportunity_model']==snapshot['board_opportunity_model']
status=json.loads(urlopen('http://127.0.0.1:8848/__status').read())
assert status['ui_generation']==brief['ui_generation']
source=ROOT/'dashboard_template.html';backup=HERE/'before/dashboard_template.html'
(HERE/'dashboard_template.html.diff').write_text(''.join(difflib.unified_diff(backup.read_text(encoding='utf-8').splitlines(keepends=True),source.read_text(encoding='utf-8').splitlines(keepends=True),fromfile='before/dashboard_template.html',tofile='dashboard_template.html')),encoding='utf-8')
scripts=re.findall(r'<script[^>]*>([\s\S]*?)</script>',source.read_text(encoding='utf-8'))
(HERE/'template_script.js').write_text('\n'.join(scripts),encoding='utf-8')
evidence=dict(changed_sources=['dashboard_template.html'],snapshot_unchanged=True,opportunities_unchanged=True,
              daily_files_unchanged=True,http_model_equal=True,generation=brief['ui_generation'],
              data_version=status['data_version'],snapshot_at=snapshot['generated_at'],pid=status['pid'],
              before_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),after_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
(HERE/'publish_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
