"""负责人只读冻结验收；输出仅写入本研究目录，不采样生产状态。"""
import copy
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config
import radar_opportunity as ro
import ui_payload

with gzip.open(ROOT / 'research/radar_opportunity_v1_20261012/frozen_inputs.json.gz', 'rt', encoding='utf-8') as stream:
    data = json.load(stream)
original = data['snapshot']
snap = copy.deepcopy(original)
model = ro.build(snap, data['quotes'], data['pool'], data['contexts'], data['histories'], data['calendar'], state={}, persist=False)
ro.validate(snap)
clean = copy.deepcopy(snap)
clean.pop('radar_opportunity')
for stock in clean['stocks'] + clean['coverage_catalog']:
    stock.pop('radar_opportunity')
assert clean == original
prior = json.loads((ROOT / 'research/radar_opportunity_v1_20261012/final_frozen_compare.json').read_text(encoding='utf-8'))
assert model['lists'] == prior['lists']
assert model['counts'] == prior['counts']
assert 'last_close_review' not in model
frozen_parameters = json.loads((ROOT / 'research/radar_acceptance_repair_20261013/before/radar_opportunity_v1/rules_frozen.json').read_text(encoding='utf-8'))['parameters']
assert json.loads(json.dumps(model['parameters'])) == json.loads(json.dumps(config.RADAR_OPPORTUNITY)) == frozen_parameters
result = dict(generated_at=snap['generated_at'], source_at=model['source_at'], counts=model['counts'],
              presentation=model['presentation'], unchanged_original_fields=True, unchanged_opportunity_lists=True,
              unchanged_parameters=True, no_future_close_archive=True, implementation_hash=ro.IMPLEMENTATION_HASH)
(OUT / 'frozen_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

brief = ui_payload.summary(snap, 'independent-frozen-round2')
brief['ui_lazy'] = False
template = (ROOT / 'dashboard_template.html').read_text(encoding='utf-8')
for marker, filename in [('/*__RADAR_SCRIPT__*/', 'radar_ui.js'), ('/*__CSV_SCRIPT__*/', 'csv_export.js'), ('/*__UI_SCRIPT__*/', 'ui_client.js')]:
    template = template.replace(marker, (ROOT / filename).read_text(encoding='utf-8'))
html = template.replace('/*__DATA__*/null', config.script_json(ui_payload.pack(brief)))
html = html.replace('<body>', '<body><div style="padding:12px;background:#fff5df">负责人第二次验收：冻结真实首轮输入，源计算时间 ' + snap['generated_at'] + '；不是当前实时行情。</div>')
(OUT / 'continuous_pending_frozen.html').write_text(html, encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
