"""记录当前运行证据；不修改快照、评分或任何交易规则。"""
import difflib
import json
from pathlib import Path
import sys
import urllib.request
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config
import board_trend
OUT=Path(__file__).parent
status=json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status',timeout=5))
snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
evidence={'status':status,'model':snap.get('board_trend_model'),
          'refresh_seconds':config.RUNTIME['refresh_seconds'],
          'snapshot_generated_at':snap['generated_at'],'stock_count':len(snap['stocks'])}
if evidence['model']:
    evidence['index_types']={kind:sum(bool(b.get('index_trend')) and b['type']==kind for b in snap['board_catalog'])
                             for kind in ['industry','theme']}
    fields={'online':'trend_online','initial':'initial_strength','pullback':'pullback','weakening':'weakening'}
    evidence['eligible_filter_counts']={kind:{key:sum(b['type']==kind and b['ranking_eligible']
                    and bool((b.get('index_trend') or {}).get('ready'))
                    and bool((b.get('index_trend') or {}).get(field)) for b in snap['board_catalog'])
                    for key,field in fields.items()} for kind in ['industry','theme']}
    evidence['diffusion_counts']={kind:sum(b['type']==kind and bool(b.get('member_diffusion')) for b in snap['board_catalog'])
                                 for kind in ['industry','theme']}
(OUT/'live-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
for name in ['scoring.py','dashboard_template.html','serve.py','make_dashboard.py']:
    before=(OUT/(name+'.before')).read_text(encoding='utf-8').splitlines(True)
    after=(ROOT/name).read_text(encoding='utf-8').splitlines(True)
    (OUT/(name+'.diff')).write_text(''.join(difflib.unified_diff(before,after,fromfile=name+'.before',tofile=name)),encoding='utf-8')
browser=(OUT/'browser_check.js').read_text(encoding='utf-8')
browser=browser.replace("  await page.route('**/__status', route=>route.abort());\n",'')
browser=browser.replace('http://127.0.0.1:8848/research/board_trend_20261009/preview.html',
                        'http://127.0.0.1:8848/dashboard.html')
browser=browser.replace('board-trend-theme.png','board-trend-theme-live.png').replace(
    'board-trend-detail.png','board-trend-detail-live.png').replace('board-trend-mobile.png','board-trend-mobile-live.png').replace(
    'board-trend-industry.png','board-trend-industry-live.png')
(OUT/'browser_live.js').write_text(browser,encoding='utf-8')
print(json.dumps({k:v for k,v in evidence.items() if k!='status'},ensure_ascii=False))
