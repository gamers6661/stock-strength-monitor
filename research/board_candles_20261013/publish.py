"""Publish a chart-only immutable generation without restarting the live service."""
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path.cwd()))
import board_chart
import config
import ui_payload

root = Path(__file__).parent


def status():
    return json.load(urlopen('http://127.0.0.1:8848/__status', timeout=10))


def judgments(full):
    return json.dumps([full.get('market_strength'), full.get('board_opportunity_model'), full.get('radar_opportunity'),
                       [r.get('market_strength') for g in ('stocks', 'coverage_catalog') for r in full.get(g, [])],
                       [{k: v for k, v in b.items() if k != 'index_chart'} for b in full.get('board_catalog', [])]], sort_keys=True)


before = status()
assert before['phase'] == 'ready' and not before['scan_active']
old = ui_payload.active_generation()
full = ui_payload.full(old)
template = ui_payload.blob(old, 'template').decode('utf8')
script = (config.ROOT/'radar_ui.js').read_text('utf8')
extra = (config.ROOT/'board_chart_ui.js').read_text('utf8')
assert template.count(script) == 1, 'Rendering changed: preserve the current main-thread publication.'
assert extra not in template
template = template.replace(script, script+'\n'+extra)
source_hash = hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest()
projected = board_chart.attach(full)
assert judgments(projected) == judgments(full)
packet, token = ui_payload.prepare(projected, template, config.ROOT/'dashboard.html')
saved = ui_payload.full(token)
assert judgments(saved) == judgments(full)
with config.pipeline_guard():
    # Do not wait behind a refresh or overwrite a publication that won the race.
    assert ui_payload.active_generation() == old
    assert hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest() == source_hash
    current = status()
    assert current['pid'] == before['pid'] and not current['scan_active']
    config.atomic_write_text(config.ROOT/'dashboard.html', template.replace('/*__DATA__*/null', config.script_json(packet)))
    ui_payload.activate(token, config.ROOT/'dashboard.html')
after = status()
assert after['pid'] == before['pid'] and after['ui_generation'] == token
result = dict(previous_generation=old, ui_generation=token, service_pid=after['pid'],
              scores_unchanged=True, snapshot_unchanged=True, snapshot_sha256=source_hash,
              ready_charts=sum(len(b['index_chart']['bars']) >= 5 for b in saved['board_catalog']),
              no_index_mapping=sum(not b['index_chart']['code'] for b in saved['board_catalog']))
(root/'publication.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
print(json.dumps(result, ensure_ascii=False, indent=2))
