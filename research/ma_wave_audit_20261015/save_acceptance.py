import json,sys
from pathlib import Path
from urllib.request import urlopen
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT))
import ma_trend
raw=(OUT/'browser_cli.txt').read_text(encoding='utf-8-sig')
b=json.loads(next(x for x in raw.splitlines() if x.startswith('{"base":')))
assert not b['errors']
s=json.loads(urlopen('http://127.0.0.1:8848/__status',timeout=15).read())
assert s['phase']=='ready' and s['last_scan_ok'] and s['code_ma_trend_hash']==s['snapshot_ma_trend_hash']==b['base']['hash']==ma_trend.IMPLEMENTATION_HASH
(OUT/'browser_acceptance.json').write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'status_after.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(version=b['base']['version'],generation=b['base']['generation'],source=b['base']['source'],
    cases=[dict(code=r['code'],name=r['name'],origin=(r['ma_trend'].get('origin')or{}).get('date'),status=r['ma_trend']['status'],exit=(r['ma_trend'].get('last_exit')or{}).get('date')) for r in b['cases']]),ensure_ascii=False))
