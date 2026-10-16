import ast,copy,gzip,importlib.util,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,ma_trend as T,strength
OUT=Path(__file__).resolve().parent
nodes=ast.parse((OUT/'baseline/config.py').read_text(encoding='utf-8')).body
expr=next(n.value for n in nodes if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MA_TREND' for t in n.targets))
old_params=eval(compile(ast.Expression(expr),'frozen-parameters','eval'),{'__builtins__':{}},{})
assert {k:v for k,v in old_params.items() if k!='version'}=={k:v for k,v in T.P.items() if k!='version'}
current_params=config.MA_TREND;config.MA_TREND=old_params
spec=importlib.util.spec_from_file_location('before_fix',OUT/'baseline/ma_trend.py');before_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(before_module)
config.MA_TREND=current_params
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
rows=s['stocks']+s.get('coverage_catalog',[]);asof=s['strength_model']['asof']
conn=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True)
hist={r['code']:[b for b in datafeed.load_kline(conn,'kline','code',r['code'],limit=160) if b['date']<=asof] for r in rows};conn.close()
cal=strength.trading_calendar(hist);changed=[];tested=0
for row in rows:
    bars=hist[row['code']]
    if not bars or bars[-1]['date']!=asof:continue
    args=(bars,cal);a=before_module.daily(*args,limit_pct=10);b=T.daily(*args,limit_pct=10)
    if a['pending']:continue
    tested+=1
    assert {k:v for k,v in a.items() if k not in ('last_exit','exits')}=={k:v for k,v in b.items() if k not in ('last_exit','exits')},row['code']
    if a['last_exit']!=b['last_exit']:
        changed.append(dict(code=row['code'],name=row['name'],origin=(b['origin'] or {}).get('date'),
            old_exit=(a['last_exit'] or {}).get('date'),new_exit=(b['last_exit'] or {}).get('date'),
            old_reason=(a['last_exit'] or {}).get('reason'),new_reason=(b['last_exit'] or {}).get('reason'),
            stage=b['stage']))
    if not b['stage'] and b['last_exit']:assert b['origin']['date']==b['last_exit']['origin']['date']
report=dict(version=T.VERSION,hash=T.IMPLEMENTATION_HASH,source=s['quote_capture_at'],asof=asof,
    tested=tested,all_parameters_except_version_unchanged=True,all_completed_day_stages_origins_and_platforms_unchanged=True,
    changed_exit_records=changed)
(OUT/'fix_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
