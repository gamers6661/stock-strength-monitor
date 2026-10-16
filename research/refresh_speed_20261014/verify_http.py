import csv,gzip,io,json,sys,time
from datetime import datetime
from statistics import median
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import market_strength as M,ui_payload
p=Path(__file__).parent;base='http://127.0.0.1:8848'
def get(path):
    with urlopen(Request(base+path,headers={'Accept-Encoding':'gzip'}),timeout=30) as response:
        b=response.read();return gzip.decompress(b) if response.headers.get('Content-Encoding')=='gzip' else b
status=json.loads(get('/__status'));token=status['ui_generation']
page=get('/dashboard.html').decode('utf8');packet,_=json.JSONDecoder().raw_decode(page.split('var DATA = ',1)[1].lstrip())
a=ui_payload.unpack(packet);b=ui_payload.unpack(json.loads(get('/__ui/summary?'+urlencode({'version':token}))))
assert a==b and b['ui_generation']==token
rows={r['code']:r for r in b['stocks']+b.get('coverage_catalog',[])}
details={}
codes=['601811','001368','605287']
for code in codes:
    d=json.loads(get('/__ui/detail?'+urlencode({'version':token,'kind':'stock','id':code})))['item']
    details[code]=d
    assert M.brief(d['market_strength'])==rows[code]['market_strength']
data=json.dumps(dict(version=token,codes=codes,contexts={})).encode()
export=urlopen(Request(base+'/__ui/export',data=data,headers={'Content-Type':'application/json'}),timeout=90).read()
(p/'actual_stock_export.csv').write_bytes(export)
parsed=list(csv.DictReader(io.StringIO(export.decode('utf-8-sig'))))
assert [r['代码'] for r in parsed]==codes
for r in parsed:
    m=details[r['代码']]['market_strength']
    assert json.loads(r['完整模型依据'])==m
    assert r['实现哈希']==M.IMPLEMENTATION_HASH==status['code_market_strength_hash']
bid=b['market_strength']['boards']['all'][0]
board=json.loads(get('/__ui/detail?'+urlencode({'version':token,'kind':'board','id':bid})))['item']
summary_board=next(r for r in b['board_catalog'] if r['id']==bid)
assert board['member_codes']==summary_board['member_codes']
assert board['market_strength']['trend_score']==summary_board['market_strength']['trend_score']
assert len(board.get('index_chart',{}).get('bars',[])) or board.get('index_chart',{}).get('reason')
for axis in ('trend','emotion'):
    ordered=b['market_strength']['stocks']['sorts'][axis]
    scores=[rows[c]['market_strength'][axis+'_score'] for c in ordered]
    values=[x for x in scores if x is not None]
    assert values==sorted(values,reverse=True)
out=dict(pid=status['pid'],generation=token,page_and_summary_same=True,page_bytes=len(page.encode()),
         details_and_csv_same_codes=codes,board_members_and_score_same=bid,full_board_chart_preserved=True,
         interval=status['refresh_interval_seconds'],factor_hash=M.IMPLEMENTATION_HASH)
published=(status.get('last_pipeline_performance') or {}).get('published_at')
if published:
    at=datetime.fromisoformat(published)
    ages=sorted((at-datetime.fromisoformat(r['intraday_quote_at'])).total_seconds()
                for r in rows.values() if r.get('intraday_quote_fresh') and r.get('intraday_quote_at'))
    if ages:
        out['valid_quote_age_seconds_at_publish']=dict(count=len(ages),minimum=ages[0],median=median(ages),
            p95=ages[min(len(ages)-1,int(.95*len(ages)))],maximum=ages[-1])
(p/'http_acceptance.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(out,ensure_ascii=False),flush=True)
