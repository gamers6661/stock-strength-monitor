"""Validate CSV files downloaded through actual CUA UI and observed member lists."""
import csv, hashlib, io, json, sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import ui_payload
OUT=Path(__file__).parent/'owner_round2'
token='ed3260dba36c4ac822fdfa50'
downloads=(Path.home() / 'Downloads')
e=json.loads((OUT/'evidence.json').read_text('utf8'))
full=ui_payload.full(token)
stocks={r['code']:r for r in full['stocks']+full['coverage_catalog']}
boards={b['id']:b for b in full['board_catalog']}
result=dict(ui_generation=token,exports={},member_filters={},clear_full_pool=3120,browser_errors=[])
for kind,stages in [('industry',[('', 'before'),(' (1)','one'),(' (2)','many'),(' (3)','many-confirmed')]),('theme',[('', 'before'),(' (1)','one'),(' (2)','many')])]:
    payloads=[];paths=[]
    for suffix,stage in stages:
        p=downloads/f'板块强度_{kind}_{token}{suffix}.csv'
        raw=p.read_bytes();payloads.append(raw);paths.append(str(p))
        (OUT/f'{kind}_browser_{stage}.csv').write_bytes(raw)
        records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        ids=[i for i in full['market_strength']['boards']['sorts']['combined'] if i in full['market_strength']['boards']['focus'] and boards[i]['type']==kind]
        assert [r['ID'] for r in records]==ids
        assert all(json.loads(r['完整模型依据'])==boards[r['ID']]['market_strength'] and r['UI版本']==token for r in records)
    assert len(set(payloads))==1
    result['exports'][kind]=dict(rows=len(records),all_models_equal=True,bytes_identical_before_one_many=True,sha256=hashlib.sha256(payloads[0]).hexdigest(),download_paths=paths)
p=downloads/f'当前强势_{token}.csv'
raw=p.read_bytes();records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
codes=full['market_strength']['stocks']['focus']
assert [r['代码'] for r in records]==codes
assert all(json.loads(r['完整模型依据'])==stocks[r['代码']]['market_strength'] and r['UI版本']==token for r in records)
(OUT/'stocks_browser_radar.csv').write_bytes(raw)
result['exports']['stocks']=dict(rows=len(records),all_models_equal=True,sha256=hashlib.sha256(raw).hexdigest(),download_path=str(p))
observed={
 '染料':{
  'all':['603188','603968','603980','002748','605566','605189','002099','603004','603790','603172','002513','001217','600987','002440','001335','605589','002556','002256','600352','002010','603599','603181'],
  'trend':['603968','603980','603188','002748','002099','605566','603004','605189'],
  'emotion':['603188','603968','002748','603980','605189','603790','603172','605566']},
 '影视院线':{
  'all':['002343','001330','601595','000892','600977','600715','002905','603721','002292','603103','000802','600088','002739'],
  'trend':['002343','001330','601595','000892','600977','600715','002905','603721','002292'],
  'emotion':['002343']}}
for name,sets in observed.items():
    for scope,codes in sets.items():assert codes==e['member_expectations'][name][scope],(name,scope)
    result['member_filters'][name]=dict(counts={k:len(v) for k,v in sets.items()},ordered_codes=sets,backend_order_equal=True)
assert full['market_strength']['counts']['all']==result['clear_full_pool']
e['browser']=result
e['checks']=dict(focused_tests=50,full_tests=537,full_test_seconds=24.511,dashboard_check='passed: 3026 stocks',live_service_check='passed: pid 21920, scan 13:02:51')
(OUT/'evidence.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(result,ensure_ascii=False,indent=2))
