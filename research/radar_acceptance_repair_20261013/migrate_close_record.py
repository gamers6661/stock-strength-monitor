"""从真实已发布快照投影昨日复核，不用今日行情/成员重新计算历史。"""
import gzip, json, hashlib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config, radar_opportunity as ro
OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'research/radar_opportunity_v1_20261012/final_published_refresh_snapshot.json.gz'
with gzip.open(SOURCE,'rt',encoding='utf-8') as f:snap=json.load(f)
review=snap['radar_opportunity']['close_review'];assert review['day']=='2026-10-12' and review['ready']
events={}
for r in snap.get('stocks',[])+snap.get('coverage_catalog',[]):
    for kind,c in r['radar_opportunity']['categories'].items():
        e=c.get('event')
        if e:events[e['event_id']]=e
bundle=ro.close_bundle(snap,review,events)
assert bundle['event_counts']['收盘确认']==112 and bundle['stock_counts']['收盘确认']==92
receipt=json.loads((SOURCE.parent/'final_published_refresh.json').read_text(encoding='utf-8'))
bundle['provenance']=dict(snapshot=str(SOURCE),sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),source_generation=receipt['after']['ui_generation'],source_data_version=str(receipt['after']['data_version']),method='只投影原真实收盘复核，不重算历史资格')
with config.pipeline_guard():
    model={'day':'2026-10-13'};ro.attach_close_archive(model,bundle,persist=True)
(OUT/'yesterday_close_record.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(day=bundle['day'],event_counts=bundle['event_counts'],stock_counts=bundle['stock_counts'],provenance=bundle['provenance']),ensure_ascii=False))
