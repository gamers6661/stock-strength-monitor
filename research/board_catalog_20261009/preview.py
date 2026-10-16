import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config
import board_center
import board_trend
import datafeed
import classification
import make_dashboard

HERE=Path(__file__).parent
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
before=copy.deepcopy(s['stocks'])
rows=s['stocks']+s.get('coverage_catalog',[])
quotes={r['code']:r for r in rows}
profiles=json.loads(config.THS_STOCK_PROFILE_CACHE.read_text(encoding='utf-8'))
if 'map' in profiles:profiles=profiles['map']
mapping,_=classification.reconcile(datafeed.build_theme_map(),profiles,datafeed.fetch_ths_concept_catalog(),quotes)
s['board_catalog']=board_center.build(s['stocks'],quotes,mapping,s['boards'],{},s['strength_model']['asof'])
s['board_catalog_version']=board_center.VERSION
for b in s['board_catalog']:
    b['member_quote_at']=s['quote_capture_at']
board_trend.attach(s,fetch=True)
assert s['stocks']==before
catalog=board_center._catalog()
for kind,names in catalog.items():
    assert names <= {b['name'] for b in s['board_catalog'] if b['type']==kind}
b=next(b for b in s['board_catalog'] if b['id']=='industry:种植业与林业')
evidence=dict(asof=s['strength_model']['asof'],stocks_unchanged=True,
    official_industries=len(catalog['industry']),official_themes=len(catalog['theme']),
    cards=len(s['board_catalog']),industry_cards=sum(b['type']=='industry' for b in s['board_catalog']),
    zero_coverage=[b['name'] for b in s['board_catalog'] if not b['pool_members']],
    target={k:b[k] for k in ('id','valid_members','source_members','member_codes','index_trend')})
(HERE/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
make_dashboard.attach_klines(s)
html=(ROOT/'dashboard_template.html').read_text(encoding='utf-8').replace(make_dashboard.PLACEHOLDER,json.dumps(s,ensure_ascii=False,separators=(',',':')))
config.atomic_write_text(HERE/'preview.html',html)
print(json.dumps({k:v for k,v in evidence.items() if k!='target'},ensure_ascii=False))
print('种植业与林业',b['valid_members'],'有效成员', (b['index_trend'] or {}).get('state'))
