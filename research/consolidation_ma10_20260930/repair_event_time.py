"""按已核验的原始时点回放恢复退出时间，收盘复核不能覆盖已有盘中退出事件。"""
import copy,json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,datafeed,strength,trend_consolidation as tc
folder=Path(__file__).resolve().parent
review=json.loads((folder/'review.json').read_text(encoding='utf-8'))
verified={r['code']:r for group in tc.GROUPS for r in review['intraday_model'][group] if r.get('trend_exited')}
snapshot=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
before=copy.deepcopy(snapshot)
model=snapshot['trend_consolidation'];changed=[]
for group in tc.GROUPS:
    for item in model[group]:
        prior=verified.get(item['code'])
        if (prior and item.get('trend_exited') and item.get('completed_at')==prior.get('completed_at') and
                item.get('trend_exit_at')==model['day']+' 15:00:00' and
                prior.get('trend_exit_at','')<item['trend_exit_at']):
            changed.append(dict(code=item['code'],name=item['name'],before=item['trend_exit_at'],after=prior['trend_exit_at']))
            item['trend_exit_at']=prior['trend_exit_at']
conn=datafeed.db()
codes={r['code'] for group in tc.GROUPS for r in model[group] if r.get('completion_confirmed')}
official={c:datafeed.load_kline(conn,'kline','code',c) for c in codes};conn.close()
tc.attach(snapshot,{}, {},{},strength.trading_calendar(official),previous={'trend_consolidation':model},
          persist=True,close_history_loader=lambda code:official.get(code,[]))
for a,b in zip(before['stocks']+before.get('coverage_catalog',[]),snapshot['stocks']+snapshot.get('coverage_catalog',[])):
    assert {k:v for k,v in a.items() if k!='trend_consolidation'}=={k:v for k,v in b.items() if k!='trend_consolidation'}
snapshot['trend_consolidation']['local_reviewed_at']=datetime.now().isoformat(sep=' ',timespec='seconds')
config.atomic_write_text(config.SNAPSHOT_JSON,json.dumps(snapshot,ensure_ascii=False,separators=(',',':')))
config.atomic_write_text(tc.DIRECTORY/(model['day']+'.json'),json.dumps(snapshot['trend_consolidation'],ensure_ascii=False,separators=(',',':')))
(folder/'event_time_evidence.json').write_text(json.dumps(dict(changes=changed,other_stock_changes=0,
    scan_generated_at=snapshot['generated_at'],local_reviewed_at=snapshot['trend_consolidation']['local_reviewed_at']),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(changed,ensure_ascii=False))
