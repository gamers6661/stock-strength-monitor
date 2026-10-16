import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,board_center,board_trend,datafeed,classification,make_dashboard
HERE=Path(__file__).parent
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
before=copy.deepcopy(s['stocks'])
rows=s['stocks']+s.get('coverage_catalog',[])
quotes={r['code']:r for r in rows}
profiles=json.loads(config.THS_STOCK_PROFILE_CACHE.read_text(encoding='utf-8')).get('profiles',{})
mapping,_=classification.reconcile(datafeed.build_theme_map(),profiles,datafeed.fetch_ths_concept_catalog(),quotes)
s['board_catalog']=board_center.build(s['stocks'],quotes,mapping,s['boards'],{},s['strength_model']['asof'])
s['board_catalog_version']=board_center.VERSION
for b in s['board_catalog']:b['member_quote_at']=s['quote_capture_at']
board_trend.attach(s,fetch=True)
assert s['stocks']==before
catalog=board_center._catalog()
official=[b for b in s['board_catalog'] if b['type']=='industry' and b['name'] in catalog['industry']]
assert len(official)==90 and not any(b['membership_stale'] for b in official)
assert all(b['source_complete'] for b in official)
targets=[]
for name,count in [('电池',107),('种植业与林业',29),('化学制药',159)]:
    b=next(b for b in official if b['name']==name)
    assert b['source_complete'] and b['detail_members_cached']==count
    targets.append({k:b[k] for k in ('id','source_members','detail_members_cached','source_complete','membership_stale','source_basis','source_checked_at','pool_members','valid_members','index_current')})
cache=json.loads((config.CACHE_DIR/'ths_industry_members.json').read_text(encoding='utf-8'))
assert not cache['stat']['failed'] and len(cache['stat']['complete_counts'])==90
e=dict(version=board_center.VERSION,stocks_unchanged=True,official_industries=90,industry_failed=0,complete_source_cards=sum(b['source_complete'] for b in official),source_members=len(cache['map']),targets=targets)
(HERE/'evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8')
(HERE/'preview.json').write_text(json.dumps(s,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
make_dashboard.attach_klines(s)
html=(ROOT/'dashboard_template.html').read_text(encoding='utf-8').replace(make_dashboard.PLACEHOLDER,json.dumps(s,ensure_ascii=False,separators=(',',':')))
config.atomic_write_text(HERE/'preview.html',html)
print(json.dumps({k:v for k,v in e.items() if k!='targets'},ensure_ascii=False))
for b in targets:print(b['id'],b['source_members'],b['pool_members'],b['valid_members'],b['index_current'].get('ready'))
