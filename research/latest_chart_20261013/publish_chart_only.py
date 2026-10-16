"""Publish only the chart layer against the active immutable UI, under the shared lock."""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import config
import ui_payload

output = Path(__file__).parent
with config.pipeline_guard():
    old_token = ui_payload.active_generation()
    full = ui_payload.full(old_token)
    template = ui_payload.blob(old_token, 'template').decode('utf-8')
    old_script = (output / 'baseline/radar_ui.js').read_text('utf-8')
    new_script = (config.ROOT / 'radar_ui.js').read_text('utf-8')
    assert template.count(old_script) == 1, 'Active rendering changed; leave its publication to the main thread.'
    template = template.replace(old_script, new_script)
    snapshot_hash = hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest()
    models = json.dumps([full.get('market_strength'), [r.get('market_strength') for g in ('stocks','coverage_catalog')
                         for r in full.get(g,[])], [b.get('market_strength') for b in full.get('board_catalog',[])]], sort_keys=True)
    packet, token = ui_payload.prepare(full, template, config.ROOT / 'dashboard.html')
    saved = ui_payload.full(token)
    assert models == json.dumps([saved.get('market_strength'), [r.get('market_strength') for g in ('stocks','coverage_catalog')
                         for r in saved.get(g,[])], [b.get('market_strength') for b in saved.get('board_catalog',[])]], sort_keys=True)
    assert snapshot_hash == hashlib.sha256(config.SNAPSHOT_JSON.read_bytes()).hexdigest()
    assert ui_payload.active_generation() == old_token
    config.atomic_write_text(config.ROOT / 'dashboard.html', template.replace('/*__DATA__*/null', config.script_json(packet)))
    ui_payload.activate(token, config.ROOT / 'dashboard.html')
    result = dict(previous_generation=old_token, ui_generation=token, scores_unchanged=True,
                  snapshot_sha256=snapshot_hash, snapshot_unchanged=True, model_version=saved['market_strength']['version'],
                  sample={c: ui_payload.detail(token,'stock',c)['chart_history'][-1]['date']
                          for c in ('002242','600241','603968')})
    (output / 'publication.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
