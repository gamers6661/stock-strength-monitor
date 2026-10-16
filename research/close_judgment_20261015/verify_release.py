import csv,json,sys,urllib.request
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,market_strength as M,ma_trend as T,emotion_relay as E,ui_payload
OUT=Path(__file__).resolve().parent
status=json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status'));s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
assert status['phase']=='ready' and status['last_publish_ok'] and status['last_scan_ok']
for kind,mod in [('market_strength',M),('ma_trend',T),('emotion_relay',E)]:
    assert status['code_'+kind+'_hash']==status['snapshot_'+kind+'_hash']==mod.IMPLEMENTATION_HASH
M.validate(s);T.validate(s);E.validate(s)
generation=status['ui_generation'];summary=ui_payload.unpack(json.load(urllib.request.urlopen('http://127.0.0.1:8848/__ui/summary?version='+generation)))
assert summary['ui_generation']==generation and summary['market_strength']==s['market_strength'] and summary['ma_trend']==s['ma_trend']
rows=s['stocks']+s.get('coverage_catalog',[]);by={r['code']:r for r in rows}
assert s['market_strength']['coverage']['trend_valid']>len(rows)*.9
assert len(s['ma_trend']['pending'])<len(rows)*.1
assert s['ma_trend']['minute_needed']==0
assert not any(r['ma_trend']['pending'] and r['ma_trend']['reason'] in ('非连续竞价报价','分钟记录未覆盖最新报价','分钟过程有缺口') for r in rows)
for r in rows:
    m=r['ma_trend']
    if m.get('quote_at'):
        assert m['mode']=='正式收盘' and m['valid_until']=='2026-10-15 23:59:59'
        assert m['completed_daily_proof']['date']=='2026-10-15'
        assert m['completed_daily_proof']['quote_at']==m['quote_at']
assert by['600825']['emotion_relay']['suspended_current'] and by['600825']['emotion_relay']['height']==10
assert len(s['emotion_relay']['lists']['sealed'])==34
assert all(m['height']>=3 for m in [by[c]['emotion_relay']['break_watch'] for c in s['emotion_relay']['lists']['broken']])
report=dict(status=status,source_at=s['ma_trend']['source_at'],close=s['market_strength']['close_verification'],
    market_coverage=s['market_strength']['coverage'],ma_status=Counter(r['ma_trend']['status'] for r in rows),ma_counts=s['ma_trend']['counts'],pending=len(s['ma_trend']['pending']),
    pending_reasons=Counter(r['ma_trend']['reason'] for r in rows if r['ma_trend']['pending']),
    emotion_coverage=s['emotion_relay']['coverage'],cases={c:dict(name=by[c]['name'],ma=by[c]['ma_trend'],market=by[c]['market_strength']) for c in ('002343','000995','600241','000993','002815','600825')})
(OUT/'release_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'收盘状态核对.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['代码','名称','均线阶段','收盘状态','待核验','原因','源行情时间','收盘判断时点','收盘依据','UI版本'])
    for r in rows:
        m=r['ma_trend'];w.writerow([r['code'],r['name'],m.get('stage_label'),m['status'],m['pending'],m['reason'],m.get('quote_at'),m.get('decision_at'),m.get('judgment_basis'),generation])
print(json.dumps({k:v for k,v in report.items() if k not in ('status','cases')},ensure_ascii=False))
print('pid',status['pid'],'generation',generation)
