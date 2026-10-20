"""实际HTTP、本页结果文件和轻量页面版本的一致性检查。"""
import json
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import stock_activity as A
import ui_payload


def get(path):
    with urlopen('http://127.0.0.1:8848'+path,timeout=30) as response:return json.load(response)


def main():
    status=get('/__status')
    model=get('/__stock_activity')
    disk=json.loads((ROOT/'cache/stock_activity_v21/latest.json').read_text(encoding='utf8'))
    assert model==disk,'HTTP结果与本页发布文件不同'
    assert model['version']==A.VERSION and model['implementation_hash']==A.IMPLEMENTATION_HASH,'实际服务结果不是当前代码'
    assert status['phase']=='ready' and status['last_scan_ok'],'全站服务未完成正常初始化'
    brief=ui_payload.unpack(get('/__ui/summary?version='+status['ui_generation']))
    assert brief['stock_activity']['version']==model['version']
    initial=brief['stock_activity']
    assert initial['implementation_hash']==model['implementation_hash']
    assert model['source_at']>=initial['source_at'],'独立结果源时间倒退'
    assert set(model['items'])==set(model['order'])
    for name,n in model['counts'].items():
        assert sum(m['list_name']==name for m in model['items'].values())==n
    for m in model['items'].values():
        assert m['factors'].get('R') is None
        if m['score'] is not None:
            assert m['eligible'] and all(m['factors'][k] is not None for k in model['rules']['enabled_factors'])
        if m['list_name']=='core':assert m['identity']['status'] in ('active','weak')
    result=dict(pid=status['pid'],rule_version=model['version'],implementation_hash=model['implementation_hash'],
                result_version=model['result_version'],ui_generation=status['ui_generation'],source_at=model['source_at'],
                mode=model['mode'],counts=model['counts'],http_disk_equal=True,initial_rule_equal=True,
                initial_result_equal=initial['result_version']==model['result_version'],
                R_uniformly_disabled=True,score_availability_valid=True)
    (Path(__file__).parent/'live_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
