import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,radar_opportunity as ro
OUT=Path(__file__).resolve().parent
old=json.loads((OUT/'first_real_event_state.json').read_text(encoding='utf-8'))
changes=[]
with config.pipeline_guard():
    state=ro.load_state()
    for key,e in state.get('events',{}).items():
        previous=old.get(key)
        if not previous or previous['event_id']!=e['event_id'] or previous['version']!=e['version']:continue
        before={k:e.get(k) for k in ('first_observed_at','first_formal_at','first_confirmed_at')}
        for time_field,price_field in [('first_observed_at','first_observed_price'),('first_formal_at','first_formal_price'),('first_confirmed_at','first_confirmed_price')]:
            at=previous.get(time_field)
            if at and (not e.get(time_field) or at<e[time_field]):e[time_field]=at;e[price_field]=previous.get(price_field)
        if before!={k:e.get(k) for k in before}:changes.append(dict(event_id=e['event_id'],before=before,after={k:e.get(k) for k in before}))
    config.atomic_write_text(ro.directory()/'state.json',json.dumps(state,ensure_ascii=False,separators=(',',':')))
    receipt=dict(source='同版本实际HTTP发布详情库，2026-10-12 14:07:14快照',
                 reason='隔离测试路径后恢复真实首次时间；当前确认序列不变，不拼接间断源采样',changes=changes)
    (OUT/'state_recovery_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print('真实首次时间恢复',len(changes),'个同一事件')
state_path=ro.directory()/'state.json'
(OUT/'state_before_final_tests.sha256').write_text(hashlib.sha256(state_path.read_bytes()).hexdigest(),encoding='ascii')
