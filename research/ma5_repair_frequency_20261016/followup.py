"""Separate immediate coverage gaps from recognition during the next five closes."""
import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
OUT=Path(__file__).parent;d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
events=json.loads((OUT/'strict_sequence_events.json').read_text(encoding='utf8'));missing=[e for e in events if not e['strict_existing_cycle']]
for e in missing:
    bs=d['histories'][e['code']];at=e['strict_confirmation_index'];first=None;steps=0;stopped=False
    for j in range(at+1,min(len(bs),at+6)):
        steps+=1;line=round(sum(b['close'] for b in bs[j-4:j+1])/5,10)
        if bs[j]['close']<line:stopped=True;break
        v=T.daily(bs[:j+1],d['calendar'],10 if e['limit_regime_known'] else None);assert not v['pending']
        if v['stage'] is not None:
            first=dict(at=bs[j]['date'],delay_days=j-at,origin=v['origin']['date'],stage=v['stage']);break
    e.update(delayed_recognition=first,follow_days_checked=steps,ma5_hold_ended=stopped,
        follow_window_incomplete=not first and not stopped and at+6>len(bs))
def counts(xs):
    return dict(immediate_gaps=len(xs),later_recognized=sum(e['delayed_recognition'] is not None for e in xs),
        still_unrecognized=sum(e['delayed_recognition'] is None and not e['follow_window_incomplete'] for e in xs),
        incomplete=sum(e['follow_window_incomplete'] for e in xs))
recent=[e for e in missing if e['strict_confirmation']>=d['calendar'][-20]]
result=dict(full=counts(missing),recent20=counts(recent),recent_cases=recent)
(OUT/'recognition_followup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'missing_with_followup.json').write_text(json.dumps(missing,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False),flush=True)
print('examples',json.dumps([{k:e.get(k) for k in ('code','name','start','strict_confirmation','delayed_recognition','ma5_hold_ended')} for e in missing if e['name'] in ('至纯科技','灵康药业','养元饮品','厦工股份')],ensure_ascii=False),flush=True)
