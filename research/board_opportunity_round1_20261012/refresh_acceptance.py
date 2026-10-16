"""真实服务重启后的刷新回执、版本推进与 HTTP 一致性证据。"""
import gzip
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import board_opportunity
import config
import ui_payload
HERE=Path(__file__).parent
BASE='http://127.0.0.1:8848'

def get(path):
    with urlopen(BASE+path,timeout=20) as r:return r.read()

def status():return json.loads(get('/__status'))

def save(name,data):
    (HERE/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

until=time.monotonic()+360
last=None
while time.monotonic()<until:
    s=status()
    progress=(s['phase'],s.get('scan_active'),s.get('snapshot_board_opportunity_version'))
    if progress!=last:print('ready progress',progress,flush=True);last=progress
    if s['phase']=='ready' and s.get('snapshot_board_opportunity_version')==board_opportunity.VERSION and not s['scan_active']:
        break
    if s['phase']=='error':raise RuntimeError(s)
    time.sleep(3)
else:raise TimeoutError('新版初始化未完成')
save('ready_before_refresh.json',s)
assert s['code_board_opportunity_version']==s['snapshot_board_opportunity_version']==board_opportunity.VERSION
before=s['data_version'];generation=s['ui_generation']
for _ in range(4):
    with urlopen(Request(BASE+'/__refresh',data=b'',method='POST'),timeout=20) as r:receipt=json.loads(r.read())
    save('refresh_receipt.json',receipt)
    print('POST receipt',receipt,flush=True)
    if receipt['status']=='started':break
    if receipt['status']=='cooldown':time.sleep(min(receipt.get('wait',5),59))
    else:time.sleep(10)
else:raise RuntimeError('刷新没有启动')
until=time.monotonic()+360
last=None
while time.monotonic()<until:
    s=status()
    progress=(s.get('scan_active'),s['refresh'].get('running'),s.get('scan_progress',{}).get('stage'),s.get('last_publish_ok'))
    if progress!=last:print('refresh progress',progress,flush=True);last=progress
    if not s['refresh']['running']:
        assert s['refresh']['ok'] is True,s['refresh']
        assert s['last_scan_ok'] is True and s['last_publish_ok'] is True,s
        assert s['data_version']!=before and s['ui_generation']!=generation
        break
    time.sleep(3)
else:raise TimeoutError('刷新发布未完成')
snapshot=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
board_opportunity.validate(snapshot)
html=get('/dashboard.html').decode('utf-8')
packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip())
brief=ui_payload.unpack(packet)
assert brief['ui_generation']==s['ui_generation']
assert brief['board_opportunity_model']==snapshot['board_opportunity_model']
assert all(b['opportunity']==next(x['opportunity'] for x in snapshot['board_catalog'] if x['id']==b['id']) for b in brief['board_catalog'])
save('refresh_final_status.json',s)
save('live_evidence.json',dict(version=board_opportunity.VERSION,pid=s['pid'],before_data_version=before,after_data_version=s['data_version'],
                            before_generation=generation,after_generation=s['ui_generation'],receipt=receipt,
                            generated_at=snapshot['generated_at'],quote_capture_at=snapshot['quote_capture_at'],
                            daily_asof=snapshot['strength_model']['asof'],counts=snapshot['board_opportunity_model']['counts'],
                            checks=board_opportunity.validate(snapshot),http_disk_equal=True))
with gzip.open(HERE/'accepted_snapshot.json.gz','wt',encoding='utf-8') as f:json.dump(snapshot,f,ensure_ascii=False)
with gzip.open(HERE/'accepted_http.html.gz','wt',encoding='utf-8') as f:f.write(html)
print('PASS',before,'->',s['data_version'],snapshot['board_opportunity_model']['counts'],flush=True)
