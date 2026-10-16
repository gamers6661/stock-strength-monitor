import gzip,json
from pathlib import Path
OUT=Path(__file__).parent
result=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf8'))
models=json.load(gzip.open(OUT/'models_comparison.json.gz','rt',encoding='utf8'))['after']
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
snap=json.loads((OUT/'snapshot_before.json').read_text(encoding='utf8'))
names={r['code']:r['name'] for r in snap['stocks']+snap.get('coverage_catalog',[])}
rows=[]
for code in result['new_ma20']:
    m=models[code];e=m['ma20_entry'];q=d['quotes'][code]
    rows.append(dict(code=code,name=names[code],origin=m['origin']['date'],rise_start=e['base_at'],
        peak=e['peak_date'],rise_pct=round(e['rise_pct'],2),rise_atr=round(e['rise_atr'],2),
        last_completed=d['histories'][code][-1]['date'],entry_observed=e['asof'],
        price=q['price'],low=q['low'],ma20_trigger=round(m['primary_support_price'],3),
        platform_floor=m['secondary_support_price'],state=m['status']))
(OUT/'sample_audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
for row in rows:print(json.dumps(row,ensure_ascii=False))
