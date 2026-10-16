"""真实午休输入回放：只用当时已经取得的11:30数据与先前采样。"""
import gzip
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import intraday
import intraday_path
import stock_strength
import strength
import trend_consolidation as tc

folder=Path(__file__).resolve().parent
with gzip.open(folder.parent/'intraday_path_20260930'/'first_published_snapshot.json.gz','rt',encoding='utf-8') as stream: snap=json.load(stream)
with gzip.open(folder/'frozen_inputs.json.gz','rt',encoding='utf-8') as stream: frozen=json.load(stream)
day=snap['quote_capture_at'][:10]
acquisition=None
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/(day+'.jsonl.gz'),'rt',encoding='utf-8') as stream:
    for line in stream:
        record=json.loads(line)
        if record['captured_at']==snap['quote_capture_at']: acquisition=record;break
assert acquisition is not None
quotes={r[0]:dict(zip(acquisition['fields'][1:],r[1:])) for r in acquisition['rows']}
klines=frozen['klines'];calendar=strength.trading_calendar({c:[b for b in bs if b['date']<day] for c,bs in klines.items()})
contexts={r['code']:intraday.align_price_basis(quotes.get(r['code'],{}),klines.get(r['code'],[]),calendar,
            observation_day=day,quote_at=r.get('intraday_judgment_at'))
          for r in snap['stocks']+snap.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
all_history=intraday_path.load(folder/'history',day)
history={'points':{c:[pt for pt in ps if str(pt.get('acquired_at') or '') < snap['quote_capture_at']]
                   for c,ps in all_history['points'].items()}}
with patch.object(stock_strength,'_daily_path',side_effect=lambda d:folder/'a_history'/(d+'.json')):
    model=tc.attach(snap,klines,quotes,contexts,calendar,history=history)
for row in model['rows']:
    assert row['quote_at']==day+' 11:30:00'
    assert row['price']==snap['boundary_prices']['midday']['prices'][row['code']]['price']
assert model['count']>0
template=(folder.parents[1]/'dashboard_template.html').read_text(encoding='utf-8')
clock='''<script>const OriginalClock=Date;class LunchReplayClock extends OriginalClock{constructor(...args){super(...(args.length?args:['2026-09-30T12:56:09+08:00']));}static now(){return new OriginalClock('2026-09-30T12:56:09+08:00').getTime();}}window.Date=LunchReplayClock;</script>'''
html=template.replace('/*__DATA__*/null',json.dumps(snap,ensure_ascii=False,separators=(',',':')))
html=html.replace('<script>\nvar DATA',clock+'<script>\nvar DATA',1)
html=html.replace('进攻与再启动监测','午休历史回放 · 仅供验收')
(folder/'午休回放.html').write_text(html,encoding='utf-8')
(folder/'lunch_evidence.json').write_text(json.dumps(dict(source=snap['generated_at'],captured_at=snap['quote_capture_at'],
    count=model['count'],last_valid_quote_at=model['last_valid_quote_at'],rows=model['rows']),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(lunch_candidates=model['count'],judgment_at=model['last_valid_quote_at'],
                     boundary_prices_match=True,no_future_samples=True),ensure_ascii=False))
