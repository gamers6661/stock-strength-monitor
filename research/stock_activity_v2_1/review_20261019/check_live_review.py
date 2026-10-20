import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
import config
import stock_activity as A
import stock_activity_engine as E
import ui_payload


def get(path):
    with urlopen('http://127.0.0.1:8848'+path,timeout=30) as r:return json.load(r)


def main():
    status=get('/__status');model=get('/__stock_activity')
    disk=json.loads((config.CACHE_DIR/'stock_activity_v21/latest.json').read_text(encoding='utf8'))
    assert status['phase']=='ready' and status['last_scan_ok']
    assert model==disk
    assert model['version']==A.VERSION and model['implementation_hash']==A.IMPLEMENTATION_HASH
    brief=ui_payload.unpack(get('/__ui/summary?version='+status['ui_generation']))
    assert brief['stock_activity']['version']==model['version']
    assert brief['stock_activity']['implementation_hash']==model['implementation_hash']
    assert set(model['items'])==set(model['order'])
    for name,n in model['counts'].items():assert n==sum(v['list_name']==name for v in model['items'].values())
    for v in model['items'].values():
        assert v['current_state'] in (None,'推进','领先保持','强势整理','转弱','失效')
        assert v['factors']['R'] is None
        if v['score'] is not None:assert v['eligible'] and all(v['factors'][k] is not None for k in model['rules']['enabled_factors'])
        if v['event'] and v['role']=='独立进攻':assert not E.confirmed(v['event'],'timing')
        if v['list_name']=='core':assert v['identity']['status'] in ('active','weak') and v['data_quality']['available']
    manifest=json.loads((HERE/'scope_before.json').read_text(encoding='utf8'))
    unchanged={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in manifest.items() if f!='shared_snapshot'}
    with config.SNAPSHOT_JSON.open('rb') as f:unchanged['shared_snapshot']=hashlib.file_digest(f,'sha256').hexdigest()==manifest['shared_snapshot']
    assert all(unchanged.values())
    report=dict(pid=status['pid'],version=model['version'],implementation_hash=model['implementation_hash'],
        result_version=model['result_version'],ui_generation=status['ui_generation'],http_disk_equal=True,
        initial_page_result_equal=brief['stock_activity']['result_version']==model['result_version'],
        source_at=model['source_at'],mode=model['mode'],counts=model['counts'],data_quality=model['data_quality'],scope_unchanged=unchanged)
    (HERE/'live_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
