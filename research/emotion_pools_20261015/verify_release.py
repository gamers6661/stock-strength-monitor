import csv,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,emotion_relay as E,ma_trend,ui_payload
OUT=Path(__file__).resolve().parent
status=json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status'))
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'));meta=s['emotion_relay'];rows={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
assert status['phase']=='ready' and status['code_emotion_relay_hash']==status['snapshot_emotion_relay_hash']==E.IMPLEMENTATION_HASH
generation=status['ui_generation']
summary=ui_payload.unpack(json.load(urllib.request.urlopen('http://127.0.0.1:8848/__ui/summary?version='+generation)))
assert summary['ui_generation']==generation and summary['emotion_relay']['implementation_hash']==meta['implementation_hash']
assert summary['emotion_relay']['source_at']==meta['source_at']
assert meta['mode']=='正式收盘' and meta['history_asof']=='2026-10-15'
assert len(meta['timeline'])==20 and len({t['date'] for t in meta['timeline']})==20
assert ma_trend.IMPLEMENTATION_HASH=='e41462e168eb78ee165013e68c4b3501502ceb3996c17813562999e61c2f2261'
E.validate(s)
assert '600825' not in meta['lists']['broken'] and '600825' not in meta['lists']['sealed']
paused=rows['600825']['emotion_relay'];assert paused['suspended_current'] and paused['height']==10 and paused['last_trade_date']=='2026-10-12'
assert meta['pools']['strength_coverage']==len(meta['lists']['sealed'])>0
for c in meta['lists']['sealed']:
    m=rows[c]['emotion_relay'];assert m['valid'] and m['sealed'] and m['mode']=='正式收盘' and m['price']==m['limit_price']
    assert m['cap_strength']['verified'] and m['cap_strength']['source_at'].startswith('2026-10-15')
for c in meta['lists']['broken']:
    m=rows[c]['emotion_relay'];b=m['break_watch'];assert b['valid'] and not b['pending'] and b['height']>=3
    assert b['date'] in [t['date'] for t in meta['timeline']]
for p in meta['promotion']:
    assert p['sealed']==len(p['success_codes'])
    assert set(p['success_codes'])<=set(meta['lists']['sealed'])
cases={c:dict(name=rows[c]['name'],model=rows[c]['emotion_relay']) for c in ['600825','600241','002242','603096','605577','603968','002343','002696','601811']}
with (OUT/'断板逐股核对.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['代码','名称','本轮首板','末板','原高度','断板日','断板前最高标','今日涨幅%','断板后累计%','最新反馈','源时间','UI版本'])
    for c in meta['lists']['broken']:
        r=rows[c];m=r['emotion_relay'];b=m['break_watch'];w.writerow([c,r['name'],b['start'],b['last'],b['height'],b['date'],b['was_market_highest'],m['feedback_pct'],b['since_break_pct'],' / '.join(b['labels']),m['quote_at'],generation])
report=dict(status=status,meta={k:v for k,v in meta.items() if k not in ('rankings','boards')},cases=cases)
(OUT/'release_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(pid=status['pid'],generation=generation,source=meta['source_at'],mode=meta['mode'],caps=len(meta['lists']['sealed']),strength=meta['pools']['strength_coverage'],broken=len(meta['lists']['broken']),promotion=[dict(height=p['height'],success=p['success_codes'],valid=p['valid'],expected=p['expected']) for p in meta['promotion']]),ensure_ascii=False))
