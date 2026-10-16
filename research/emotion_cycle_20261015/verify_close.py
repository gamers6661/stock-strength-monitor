import csv,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config,emotion_relay as E,ma_trend
OUT=Path(__file__).resolve().parent
status=json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status'))
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'));meta=s['emotion_relay'];rows={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
assert status['phase']=='ready' and status['code_emotion_relay_hash']==status['snapshot_emotion_relay_hash']==E.IMPLEMENTATION_HASH
assert meta['mode']=='正式收盘' and meta['history_asof']=='2026-10-15'
assert len(meta['timeline'])==20 and len({t['date'] for t in meta['timeline']})==20
assert meta['timeline'][-1]['date']=='2026-10-15'
E.validate(s)
assert ma_trend.IMPLEMENTATION_HASH=='e41462e168eb78ee165013e68c4b3501502ceb3996c17813562999e61c2f2261'
paused=rows['600825']['emotion_relay'];assert paused['suspended_current'] and paused['height']==10 and paused['price']==13.78 and paused['last_trade_date']=='2026-10-12'
assert paused['feedback_pct'] is None and paused['sealed'] is None
assert paused['history'][-1]['date']=='2026-10-15' and paused['history'][-1]['halted']
assert all(w['asof']=='2026-10-15' for w in paused['regulation']['reference']['windows'])
for c in ('600825','002343'):
 assert all(w['deviation_pp'] is not None for w in rows[c]['emotion_relay']['regulation']['reference']['windows'])
for row in rows.values():
 m=row['emotion_relay']
 if m['continuation']:assert m['valid'] and m['sealed'] and all(n['first_board_date']==n['date'] for n in m['continuation'])
bydate=meta['timeline'];names=['date','valid','expected','suspended','limit_count','highest','retained_highest','unknown']
with (OUT/'正式收盘20日概况.csv').open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=names);writer.writeheader();writer.writerows(bydate)
with (OUT/'正式收盘逐股20日核算.csv').open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.writer(f);writer.writerow(['交易日','代码','名称','原价收盘','封板','全天停牌','完成高度','链完整','原因','UI版本'])
 for day in [t['date'] for t in bydate]:
  for c,r in rows.items():
   p=next((p for p in r['emotion_relay']['history'] if p['date']==day),dict(sealed=None,height=None,exact=False,reason='当日未取得可核验记录'))
   writer.writerow([day,c,r['name'],p.get('close'),p.get('sealed'),p.get('halted'),p.get('height'),p.get('exact'),p.get('reason'),status['ui_generation']])
report=dict(status=status,meta={k:v for k,v in meta.items() if k not in ('rankings','boards')},cases={c:rows[c]['emotion_relay'] for c in ('600825','002343','601811','605577')},assertions='正式收盘、20日滚动、停牌高度、最新指数参考窗口、收盘断板候选退出、MA不变及服务代码快照一致')
(OUT/'close_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(pid=status['pid'],generation=status['ui_generation'],source=meta['source_at'],mode=meta['mode'],days=[meta['history_from'],meta['history_asof']],cycle=meta['cycles']['cycle_highest'],highest=meta['highest_live'],coverage=meta['coverage'],disclosures=meta['cycles']['disclosure_coverage'],continuation=meta['lists']['continuation']),ensure_ascii=False))
print('cases',[(c,rows[c]['name'],rows[c]['emotion_relay']['height'],rows[c]['emotion_relay']['roles']) for c in ('600825','002343','601811','605577')])
