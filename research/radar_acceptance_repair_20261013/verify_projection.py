import copy,gzip,json,time,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,radar_opportunity as ro,ui_payload
OUT=Path(__file__).resolve().parent
with gzip.open(ROOT/'research/radar_opportunity_v1_20261012/frozen_inputs.json.gz','rt',encoding='utf-8') as f:data=json.load(f)
original=data['snapshot'];snap=copy.deepcopy(original);start=time.perf_counter()
model=ro.build(snap,data['quotes'],data['pool'],data['contexts'],data['histories'],data['calendar'],state={},persist=False)
ro.validate(snap)
clean=copy.deepcopy(snap);clean.pop('radar_opportunity')
for r in clean['stocks']+clean['coverage_catalog']:r.pop('radar_opportunity')
assert clean==original
prior=json.loads((ROOT/'research/radar_opportunity_v1_20261012/final_frozen_compare.json').read_text(encoding='utf-8'))
assert model['lists']==prior['lists'] and model['counts']==prior['counts']
assert 'last_close_review' not in model,'盘中重放不能读取未来同日收盘结果'
report=dict(original_fields_identical=True,opportunity_lists_identical=True,parameters_unchanged=True,seconds=time.perf_counter()-start,implementation_hash=ro.IMPLEMENTATION_HASH,lists=model['lists'],counts=model['counts'])
assert json.loads(json.dumps(config.RADAR_OPPORTUNITY))==json.loads((OUT/'before/radar_opportunity_v1/rules_frozen.json').read_text(encoding='utf-8'))['parameters']
(OUT/'frozen_compare.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

archive=json.loads((OUT/'yesterday_close_record.json').read_text(encoding='utf-8'))
auction=json.loads((OUT/'before/snapshot.json').read_text(encoding='utf-8'))
assert auction['session'] in ('集合竞价','竞价结束')
m=auction['radar_opportunity'];m.update(presentation=ro.presentation(auction['session'],False),last_close_review=archive,repair_version=ro.REPAIR_VERSION)
m['market'].update(enabled=False,reason=m['presentation']['market_reason'])
with gzip.open(ROOT/'research/radar_opportunity_v1_20261012/final_published_refresh_snapshot.json.gz','rt',encoding='utf-8') as f:closed=json.load(f)
closed['radar_opportunity'].update(presentation=ro.presentation('已收盘',False),last_close_review=archive,repair_version=ro.REPAIR_VERSION)
tpl=(ROOT/'dashboard_template.html').read_text(encoding='utf-8').replace('/*__RADAR_SCRIPT__*/',(ROOT/'radar_ui.js').read_text(encoding='utf-8')).replace('/*__CSV_SCRIPT__*/',(ROOT/'csv_export.js').read_text(encoding='utf-8')).replace('/*__UI_SCRIPT__*/',(ROOT/'ui_client.js').read_text(encoding='utf-8'))
for label,value in [('auction_frozen',auction),('close_frozen',closed)]:
    value['ui_generation']=label;value['ui_lazy']=False
    html=tpl.replace('/*__DATA__*/null',config.script_json(ui_payload.pack(value))).replace('<body>','<body><div style="padding:12px;background:#fff5df">冻结真实快照投影验收：'+label+'，源计算时间 '+value['generated_at']+'；不是当前实时行情。</div>')
    config.atomic_write_text(OUT/(label+'.html'),html)
print(json.dumps({k:v for k,v in report.items() if k!='lists'},ensure_ascii=False))
