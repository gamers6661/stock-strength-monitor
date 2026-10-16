"""Publish only the stock-detail candle fix over the currently served UI/data.

Does not read the work-in-progress dashboard template or emotion UI, recalculate
models, refresh quotes, or restart the service.
"""
from pathlib import Path
import gzip,hashlib,json,shutil,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,ui_payload as U,make_dashboard,datafeed
OUT=Path(__file__).resolve().parent
old=U.active_generation();before=(OUT/'radar_ui.before.js').read_text(encoding='utf-8')
after=(ROOT/'radar_ui.js').read_text(encoding='utf-8')
template=U.blob(old,'template').decode('utf-8')
prior=OUT/'last_published_radar.js'
if template.count(before)!=1 and prior.exists():before=prior.read_text(encoding='utf-8')
if template.count(before)!=1:
    prefix=before[:400];suffix=before[-400:]
    assert template.count(prefix)==1 and template.count(suffix)==1
    start=template.index(prefix);end=template.index(suffix,start)+len(suffix)
    candidate=template[start:end]
    def without_stock_renderer(text):
        a=text.index('function showStock(code,boardId)');b=text.index('\nvar MS_CHART=null;',a)
        return text[:a]+text[b:]
    assert without_stock_renderer(candidate)==without_stock_renderer(before)
    before=candidate
assert template.count(before)==1,'Published radar source changed; do not overwrite another update'
new_template=template.replace(before,after,1)
assert template.replace(before,'CANDLE_SCRIPT',1)==new_template.replace(after,'CANDLE_SCRIPT',1)
full=U.full(old);frozen_hash=hashlib.sha256(U.dumps(full).encode()).hexdigest()
before_models=[(r['code'],U.dumps(r.get('ma_trend')),U.dumps(r.get('market_strength')),U.dumps(r.get('emotion_relay'))) for r in full['stocks']+full.get('coverage_catalog',[])]
asof=(full.get('strength_model') or {}).get('asof');added=[]
conn=datafeed.db()
try:
    for row in full['stocks']+full.get('coverage_catalog',[]):
        if (row.get('emotion_relay') or {}).get('suspended_current'):continue
        bars=datafeed.load_kline(conn,'kline','code',row['code'],limit=60)
        if make_dashboard.attach_completed_candles(row,bars,asof or row.get('signal_date')):added.append(row['code'])
finally:conn.close()
assert before_models==[(r['code'],U.dumps(r.get('ma_trend')),U.dumps(r.get('market_strength')),U.dumps(r.get('emotion_relay'))) for r in full['stocks']+full.get('coverage_catalog',[])]
published_data_hash=hashlib.sha256(U.dumps(full).encode()).hexdigest()
stage=OUT/'frozen_support';stage.mkdir(exist_ok=True)
for name in ('ui_client.js','csv_runner.js','stock_list_fields.json'):
    shutil.copy2(ROOT/name,stage/name)
(stage/'csv_export.js').write_bytes(U.blob(old,'csv_formatter'))
# Keep the data and formatter frozen; only the rendering template changes.
saved_root=config.ROOT;saved_projection=U.chart_projection
try:
    config.ROOT=stage;U.chart_projection=lambda data:data
    packet,new=U.prepare(full,new_template,ROOT/'dashboard.html')
finally:config.ROOT=saved_root;U.chart_projection=saved_projection
assert hashlib.sha256(U.blob(new,'full')).hexdigest()==published_data_hash
assert U.blob(old,'csv_formatter')==U.blob(new,'csv_formatter')
html=new_template.replace('/*__DATA__*/null',config.script_json(packet))
with config.pipeline_guard():
    assert U.active_generation()==old,'A newer UI was published; preserve it'
    config.atomic_write_text(ROOT/'dashboard.html',html)
    U.activate(new,ROOT/'dashboard.html')
prior.write_text(after,encoding='utf-8')
report=dict(previous_generation=old,generation=new,models_unchanged=True,csv_formatter_unchanged=True,
    source_at=full['quote_capture_at'],added_chart_histories=len(added),only_stock_detail_render_and_chart_data_changed=True)
(OUT/'publish_result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
