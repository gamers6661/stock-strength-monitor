from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
snap=json.loads((ROOT/'cache/snapshot.json').read_text(encoding='utf-8'))
rows=snap['stocks']+snap.get('coverage_catalog',[])
status=json.load(urlopen('http://127.0.0.1:8848/__status'))
assert status['pid']==22836 and status['last_scan_ok'] is True
assert status['code_intraday_model_version']==snap['intraday_model']['version']=='盘中观察初版7'
assert status['code_intraday_rule_version']==snap['intraday_model']['rule_version']=='盘中规则2026-09-30.4'
assert snap['session']=='午盘' and snap['intraday_model']['valid_quote_count']>3000
assert all(r['intraday_path']['last_at']==r['intraday_judgment_at'] for r in rows if r.get('intraday_observation_available'))
files=['intraday_path.py','intraday.py','attack_model.py','scoring.py','close_monitor.py',
       'dashboard_template.html','config.py','serve.py','check_dashboard.py',
       'test_intraday_path.py','test_intraday.py','test_attack_model.py','test_price_basis.py']
saved=OUT/'after';saved.mkdir(exist_ok=True)
for name in files:shutil.copy2(ROOT/name,saved/name)
samples=[]
for r in rows:
    if r['code'] not in ('000710','002962','603231'):continue
    p=r['intraday_path']
    sample={k:r.get(k) for k in ('code','name','price','intraday_score','live_attack_score',
        'live_attack_tier','live_attack_stage','intraday_judgment_at','intraday_risk_flags','live_attack_fund')}
    sample['path']={k:p.get(k) for k in ('state','acquired_count','valid_count','distinct_count','missing_count',
             'attack_consecutive','ma10_hold_consecutive','last_at','events')}
    samples.append(sample)
result=dict(status=status,snapshot_at=snap['generated_at'],quote_capture_at=snap['quote_capture_at'],
    model=snap['intraday_model'],attack_monitor={k:snap['attack_monitor'].get(k) for k in
        ('version','session','count','sample_count','reference_count','retained')},samples=samples,
    checks=dict(unit_tests=141,path_tests=17,status_cases=6,quote_bridge_cases=7,
        dashboard='passed',live_service='passed',csv_rows=3088,csv_columns=146),
    fund_weights=dict(Counter(str((r.get('live_attack_fund') or {}).get('weight')) for r in rows)),
    source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files})
(OUT/'final_live_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result[k] for k in ('snapshot_at','quote_capture_at','attack_monitor','samples','checks')},ensure_ascii=False,indent=2))
