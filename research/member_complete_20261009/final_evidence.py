import json,sys,math
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,board_center
def get(path):
    with urlopen('http://127.0.0.1:8848'+path,timeout=20) as r:return r.read().decode('utf-8')
def equivalent(a,b):
    # 页面重新计算均线时可能有浮点末位差异，成员、状态及来源仍逐项严格核对。
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    if isinstance(a,(int,float)) and isinstance(b,(int,float)) and not isinstance(a,bool) and not isinstance(b,bool):
        return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)
    return type(a)==type(b) and a==b
st=json.loads(get('/__status'))
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
served,_=json.JSONDecoder().raw_decode(get('/dashboard.html').split('var DATA = ',1)[1].lstrip())
assert st['phase']=='ready' and st['last_publish_ok']
assert st['code_board_catalog_version']==st['snapshot_board_catalog_version']==s['board_catalog_version']==served['board_catalog_version']==board_center.VERSION
assert equivalent(s['board_catalog'],served['board_catalog'])
assert st['member_refresh']['interval_days']==served['member_refresh']['interval_days']==7
assert config.RUNTIME['refresh_seconds']==300
c=json.loads((config.CACHE_DIR/'ths_industry_members.json').read_text(encoding='utf-8'))
assert not c['stat']['failed'] and not c['stat']['partial']
official=[b for b in s['board_catalog'] if b['type']=='industry' and b['catalog_listed']]
assert len(official)==90 and all(b['source_complete'] and not b['membership_stale'] for b in official)
for b in official:
    codes={code for code,names in c['map'].items() if b['name'] in names}
    assert len(codes)==b['source_members']==c['stat']['complete_counts'][b['name']]
    assert set(b['member_codes'])<=codes
targets=[]
for name,count in [('电池',107),('种植业与林业',29),('化学制药',159),('公路铁路运输',32),('钢铁',44)]:
    b=next(b for b in official if b['name']==name)
    assert b['source_members']==count
    targets.append({k:b[k] for k in ('id','source_members','pool_members','valid_members','source_complete','membership_stale','source_basis','source_checked_at','index_current')})
e=dict(pid=st['pid'],version=board_center.VERSION,snapshot_at=s['generated_at'],policy=st['member_refresh'],refresh_seconds=300,official_industries=90,industry_failed=0,source_members=len(c['map']),snapshot_and_page_match=True,targets=targets)
Path(__file__).with_name('live-evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in e.items() if k!='targets'},ensure_ascii=False))
