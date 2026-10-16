import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import copy,gzip,json,sqlite3,time,hashlib,csv,subprocess
import config,datafeed,strength,intraday,radar,radar_opportunity as ro

OUT=Path(__file__).resolve().parent;BEFORE=OUT/'before'
snap=json.loads((BEFORE/'frozen_snapshot.json').read_text(encoding='utf-8'))
with gzip.open(BEFORE/(snap['generated_at'][:10]+'.jsonl.gz'),'rt',encoding='utf-8') as stream:
    records=[json.loads(line) for line in stream]
record=next(r for r in records if r['captured_at']==snap['quote_capture_at'])
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
pool=json.loads((BEFORE/'cache'/'pool.json').read_text(encoding='utf-8'))
with sqlite3.connect(BEFORE/'market.db') as conn:
    histories={c:datafeed.load_kline(conn,'kline','code',c,limit=160) for c in pool}
calendar=strength.trading_calendar({c:strength.completed(v) for c,v in histories.items()})
contexts={c:intraday.align_price_basis(q,histories.get(c,[]),calendar,record['captured_at'][:10]) for c,q in quotes.items()}
frozen=dict(snapshot=snap,quotes=quotes,pool=pool,histories=histories,calendar=calendar,contexts=contexts)
with gzip.open(OUT/'frozen_inputs.json.gz','wt',encoding='utf-8') as stream:stream.write(json.dumps(frozen,ensure_ascii=False,separators=(',',':')))
new=copy.deepcopy(snap);before=time.perf_counter()
model=radar.build_opportunities(new,quotes,pool,contexts,histories,calendar,state={},persist=False)
elapsed=time.perf_counter()-before;ro.validate(new)
with gzip.open(OUT/'frozen_result.json.gz','wt',encoding='utf-8') as stream:stream.write(json.dumps(new,ensure_ascii=False,separators=(',',':')))
clean=copy.deepcopy(new);clean.pop('radar_opportunity')
for r in clean['stocks']+clean['coverage_catalog']:r.pop('radar_opportunity')
assert clean==snap,'新模块更改了旧快照字段'
# Same frozen rows through old and new formatter: all original columns identical.
contexts_csv={'useCompletedClose':False}
def csv_result(formatter,rows):
    payload={'rows':rows,'data':{'generated_at':snap['generated_at'],'ui_generation':'frozen-input'},'contexts':contexts_csv,'formatter':formatter}
    result=subprocess.run(['node',str(ROOT/'csv_runner.js')],input=json.dumps(payload,ensure_ascii=False).encode('utf-8'),capture_output=True,check=True)
    return list(csv.reader(result.stdout.decode('utf-8-sig').splitlines()))
old_csv=csv_result((BEFORE/'csv_export.js').read_text(encoding='utf-8'),snap['stocks'])
new_csv=csv_result((ROOT/'csv_export.js').read_text(encoding='utf-8'),new['stocks'])
assert all(a==b[:228] for a,b in zip(old_csv,new_csv)) and len(old_csv)==len(new_csv)
report=dict(frozen_at=record['captured_at'],generated_at=snap['generated_at'],old_fields_identical=True,old_csv_228_columns_identical=True,
            stocks=len(snap['stocks']),coverage=len(snap['coverage_catalog']),boards=len(snap['board_catalog']),quote_count=len(quotes),
            added_compute_seconds=elapsed,market=model['market'],counts=model['counts'],lists=model['lists'],
            files={'input_sha256':hashlib.sha256((OUT/'frozen_inputs.json.gz').read_bytes()).hexdigest()})
(OUT/'frozen_compare.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'frozen_all_reasons.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    w=csv.writer(stream);w.writerow(['代码','名称','原日线档','原进攻候选','原初步启动','新状态','标签','R0','E0','逐类未通过原因'])
    rows={r['code']:r for r in snap['stocks']+snap['coverage_catalog']}
    for code,r in model['by_code'].items():
        old=rows[code];full=next(row['radar_opportunity'] for row in new['stocks']+new['coverage_catalog'] if row['code']==code)
        w.writerow([code,r['name'],old.get('trend_tier'),old.get('attack_watch_candidate'),old.get('startup_candidate'),r['status'],'、'.join(r['labels']),r['R0'],r['E0'],json.dumps(full['reasons'],ensure_ascii=False)])
print(json.dumps({k:report[k] for k in ('old_fields_identical','old_csv_228_columns_identical','added_compute_seconds','counts')},ensure_ascii=False))
