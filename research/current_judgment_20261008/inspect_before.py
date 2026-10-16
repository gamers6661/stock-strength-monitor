"""两只截图股票与全池相同展示问题的证据。"""
from collections import Counter
import gzip
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import scoring
import strength
import intraday

snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
rows=snap['stocks']+snap.get('coverage_catalog',[])
series=scoring.formal_histories(['600241','603867'])
calendar=strength.trading_calendar({c:strength.completed(b) for c,b in scoring.formal_histories([r['code'] for r in rows]).items()})
selected=[]
for row in rows:
    if row['code'] not in series:continue
    bars=[b for b in series[row['code']] if b['date']<=snap['strength_model']['asof']]
    selected.append(dict(code=row['code'],name=row['name'],daily_count=len(bars),history_last=bars[-1] if bars else None,
      last20=[{k:b.get(k) for k in ('date','close','volume','price_basis','price_basis_source')} for b in bars[-20:]],
      current={k:row.get(k) for k in ('price','change_pct','intraday_quote_at','intraday_judgment_at','intraday_quote_fresh','intraday_observation_available','intraday_risk_flags','intraday_trend_ok','intraday_ma10','intraday_ma20','live_attack_stage','live_attack_pattern','live_attack_tier','live_attack_score')},
      consolidation=row.get('trend_consolidation'),structure=row.get('wyckoff_structure'),context=row.get('session_context')))
result=dict(snapshot_at=snap['generated_at'],asof=snap['strength_model']['asof'],stocks=selected,
  rejected_count=sum((r.get('trend_consolidation') or {}).get('eligible') is False for r in rows),
  reject_reasons=dict(Counter((r.get('trend_consolidation') or {}).get('reason') for r in rows)),
  structure_count=snap['wyckoff_structure']['count'])
out=Path(__file__).parent;out.mkdir(parents=True,exist_ok=True)
(out/'before.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
backup=ROOT/'backups/latest_before_current_judgment';backup.mkdir(parents=True,exist_ok=True)
if not (backup/'source.zip').exists():
    with zipfile.ZipFile(backup/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.iterdir():
            if p.is_file() and (p.suffix in ('.py','.pyw','.ps1','.bat','.vbs') or p.name=='dashboard_template.html'):z.write(p,p.name)
    with gzip.open(backup/'snapshot.json.gz','wb') as f:f.write(config.SNAPSHOT_JSON.read_bytes())
    (backup/'README.md').write_text('最新判断展示修复前备份，仅供恢复，不参与新版导入。\n',encoding='utf-8')
print(json.dumps(dict(result,stocks=[{k:v for k,v in s.items() if k!='last20'} for s in selected]),ensure_ascii=False))
