import sys,json,time,gzip
from pathlib import Path
from urllib.request import urlopen,Request
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
OUT=Path(__file__).resolve().parent
name=sys.argv[1] if len(sys.argv)>1 else 'manual_refresh'
def get():
    with urlopen('http://127.0.0.1:8848/__status',timeout=20) as r:return json.load(r)
deadline=time.time()+900
while get()['phase']!='ready':
    if time.time()>deadline:raise RuntimeError('初始化未就绪')
    time.sleep(10)
before=get()
with urlopen(Request('http://127.0.0.1:8848/__refresh',data=b'',method='POST'),timeout=30) as r:accepted=json.load(r)
print(json.dumps({'accepted':accepted,'before_version':before['data_version']},ensure_ascii=False),flush=True)
while time.time()<deadline:
    after=get();refresh=after['refresh']
    if not refresh['running'] and refresh.get('finished_at'):
        if not refresh.get('ok'):raise RuntimeError(str(refresh))
        if after['data_version']==before['data_version']:raise RuntimeError('data_version未变化')
        receipt={'before':before,'accepted':accepted,'after':after}
        (OUT/(name+'.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        with gzip.open(OUT/(name+'_snapshot.json.gz'),'wb') as f:f.write(config.SNAPSHOT_JSON.read_bytes())
        print(json.dumps({'after_version':after['data_version'],'generation':after['ui_generation'],'counts':after['snapshot_radar_opportunity_counts']},ensure_ascii=False),flush=True)
        break
    time.sleep(10)
else:raise RuntimeError('刷新超时')
