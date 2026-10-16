import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,radar_opportunity as ro,ui_payload
OUT=Path(__file__).resolve().parent
archive=json.loads((OUT/'yesterday_close_record.json').read_text(encoding='utf-8'))
auction=json.loads((OUT/'before/snapshot.json').read_text(encoding='utf-8'))
with gzip.open(ROOT/'research/radar_opportunity_v1_20261012/final_published_refresh_snapshot.json.gz','rt',encoding='utf-8') as f:closed=json.load(f)
tpl=(ROOT/'dashboard_template.html').read_text(encoding='utf-8').replace('/*__RADAR_SCRIPT__*/',(ROOT/'radar_ui.js').read_text(encoding='utf-8')).replace('/*__CSV_SCRIPT__*/',(ROOT/'csv_export.js').read_text(encoding='utf-8')).replace('/*__UI_SCRIPT__*/',(ROOT/'ui_client.js').read_text(encoding='utf-8'))
for label,value in [('auction_frozen',auction),('close_frozen',closed)]:
    m=value['radar_opportunity'];m.update(presentation=ro.presentation(value['session'],False),last_close_review=archive,repair_version=ro.REPAIR_VERSION)
    m['market'].update(enabled=m['presentation']['market_enabled'],reason=m['presentation']['market_reason'])
    if not m['market']['enabled']:
        m['market']['coverage_pct']=None
        for row in value['stocks']+value['coverage_catalog']:
            for c in row.get('radar_opportunity',{}).get('admission_checks',[]):
                if c['key']=='主板报价覆盖%':c.update(actual=None,passed=None)
    value=ui_payload.summary(value,label);value['ui_lazy']=False
    html=tpl.replace('/*__DATA__*/null',config.script_json(ui_payload.pack(value))).replace('<body>','<body><div style="padding:12px;background:#fff5df">冻结真实快照投影验收：'+label+'，源计算时间 '+value['generated_at']+'；不是当前实时行情。</div>')
    config.atomic_write_text(OUT/(label+'.html'),html)
    print(label,len(html))
