"""冻结现有快照、对应采集原文、历史日线和采样路径，研究回放不修改线上缓存。"""
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
import intraday
import intraday_path
import datafeed

folder=Path(__file__).resolve().parent
snap=json.loads((folder/'before_snapshot.json').read_text(encoding='utf-8'))
day=snap['quote_capture_at'][:10]
capture=snap['quote_capture_at']
chosen=None
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/(day+'.jsonl.gz'),'rt',encoding='utf-8') as stream:
    for line in stream:
        r=json.loads(line)
        if r['captured_at']==capture: chosen=r
assert chosen is not None, '找不到该快照对应的原始行情采集'
quotes={r[0]:dict(zip(chosen['fields'][1:],r[1:])) for r in chosen['rows']}
codes={r['code'] for r in snap['stocks']+snap.get('coverage_catalog',[])}
conn=sqlite3.connect('file:'+str(config.KLINE_DB)+'?mode=ro',uri=True)
conn.execute('BEGIN')
klines={c:datafeed.load_kline(conn,'kline','code',c,limit=65) for c in sorted(codes)}
conn.close()
with gzip.open(folder/'frozen_inputs.json.gz','wt',encoding='utf-8') as stream:
    json.dump(dict(snapshot=snap,quotes=quotes,klines=klines,acquisition=chosen),stream,ensure_ascii=False)
history_folder=folder/'history';history_folder.mkdir(exist_ok=True)
with (intraday.HISTORY_DIR/(day+'.jsonl')).open(encoding='utf-8') as source,(history_folder/(day+'.jsonl')).open('w',encoding='utf-8') as target:
    for line in source:
        r=json.loads(line)
        if r['scan_at'] < snap['generated_at']: target.write(line)
a_folder=folder/'a_history';a_folder.mkdir(exist_ok=True)
for source in (config.CACHE_DIR/'stock_strength_daily'/'v6').glob('*.json'):
    if source.stem<=snap['strength_model']['asof']: shutil.copy2(source,a_folder/source.name)
print(json.dumps(dict(captured_at=capture,stocks=len(codes),quotes=len(quotes),
                      kline_codes=sum(bool(v) for v in klines.values())),ensure_ascii=False))
