"""同一实施前快照及其真实原始采集批；不写生产状态。"""
import copy
import csv
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import board_opportunity as B
import board_trend
import config
import ui_payload

HERE=Path(__file__).parent
original=json.loads((HERE/'before/snapshot.json').read_text(encoding='utf-8'))
quotes=json.loads((HERE/'before/quotes.json').read_text(encoding='utf-8'))
pool=json.loads((HERE/'before/pool.json').read_text(encoding='utf-8'))
after=copy.deepcopy(original)
with tempfile.TemporaryDirectory() as tmp:
    B.enrich(after,quotes,pool,persist=False,history_dir=tmp)
B.validate(after)
clean=copy.deepcopy(after)
clean.pop('board_opportunity_model')
for b in clean['board_catalog']:b.pop('opportunity')
assert clean==original, '新增字段以外的原有快照发生变化'
brief=ui_payload.unpack(ui_payload.pack(ui_payload.summary(after,'frozen')))
assert brief['board_opportunity_model']==after['board_opportunity_model']
assert all(a['opportunity']==b['opportunity'] for a,b in zip(brief['board_catalog'],after['board_catalog']))
spec=importlib.util.spec_from_file_location('before_board_trend', HERE/'before/board_trend.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
days=original['board_trend_model']['calendar']
checked=0
for b in original['board_catalog']:
    d=b.get('index_trend') or {}
    if not d.get('ready'):continue
    bars=board_trend.load(d['code'])
    bars=[v for v in bars if v['date']<=original['strength_model']['asof']]
    trace=[]
    assert old.replay(copy.deepcopy(bars),days)==board_trend.replay(copy.deepcopy(bars),days,observer=lambda *row:trace.append(row))
    checked+=1
result=dict(input_generated_at=original['generated_at'],input_quote_capture_at=original['quote_capture_at'],
            stock_rows=len(original['stocks']),coverage_rows=len(original['coverage_catalog']),board_rows=len(original['board_catalog']),
            all_existing_fields_identical=True,stock_scores_and_tiers_identical=True,members_identical=True,index_fields_identical=True,
            index_replay_before_after_identical=checked,counts=after['board_opportunity_model']['counts'],
            market=after['board_opportunity_model']['market'],refresh_seconds=config.RUNTIME['refresh_seconds'])
(HERE/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(HERE/'frozen_after.json').write_text(json.dumps(after,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
with (HERE/'冻结输入资格变化.csv').open('w',encoding='utf-8-sig',newline='') as f:
    fields=['id','type','name','before_index_state','before_index_watch','before_opportunity','daily_mainline','mainline','startup_raw','startup_confirmed','restart_raw','restart_confirmed','status','R5','E5','R0','E0','U0','daily_count','quote_count','quote_coverage','background']
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for b in after['board_catalog']:
        o=b['opportunity'];d=o['daily'];q=o['current'];idx=b.get('index_current') or {}
        w.writerow(dict(id=b['id'],type=b['type'],name=b['name'],before_index_state=idx.get('state'),before_index_watch=idx.get('priority_observation'),before_opportunity='未启用',
                        daily_mainline=o['daily_mainline'],mainline=o['qualifications']['mainline'],startup_raw=o['startup_raw'],startup_confirmed=o['qualifications']['startup'],
                        restart_raw=o['restart_raw'],restart_confirmed=o['qualifications']['restart'],status=o['status'],R5=d['R5'],E5=d['E5'],R0=q['R0'],E0=q['E0'],U0=q['U0'],
                        daily_count=d['valid_count'],quote_count=q['valid_count'],quote_coverage=q['coverage_pct'],background=o['background']['source'] or o['background']['reason']))
print(json.dumps(result,ensure_ascii=False))
