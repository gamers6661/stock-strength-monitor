from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import scoring
import strength
snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
main={r['code'] for r in snap['stocks']}
rows=snap['stocks']+snap.get('coverage_catalog',[])
gaps=[r for r in rows if not r['session_context']['history_evidence']['valid']]
series=scoring.formal_histories([r['code'] for r in gaps])
asof=snap['strength_model']['asof']
calendar=strength.trading_calendar({c:[b for b in bars if b['date']<=asof] for c,bars in scoring.formal_histories([r['code'] for r in rows]).items()})[-40:]
out=[]
for r in gaps:
    b=[b for b in series.get(r['code'],[]) if b['date']<=asof]
    out.append(dict(code=r['code'],name=r['name'],in_main=r['code'] in main,
       reason=r['session_context']['history_evidence']['reason'],trade_status=r.get('trade_status'),
       coverage_reason=r.get('reason_text'),list_days=r.get('list_days'),
       first=b[0]['date'] if b else None,last=b[-1]['date'] if b else None,count=len(b),
       missing_dates=[d for d in calendar if d not in {x['date'] for x in b}]))
Path(__file__).with_name('history_gaps.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(main_gaps=[r for r in out if r['in_main']],outside=len([r for r in out if not r['in_main']]),
   outside_reasons=dict(Counter(str(r['coverage_reason']) for r in out if not r['in_main']))),ensure_ascii=False))
