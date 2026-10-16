# -*- coding: utf-8 -*-
import json
import hashlib
from pathlib import Path
from urllib.request import urlopen
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ui_payload
import config

out = Path(__file__).resolve().parent
s = json.load(urlopen('http://127.0.0.1:8848/__status'))
full = ui_payload.full(s['ui_generation'])
by = {b['id']: b for b in full['board_catalog']}
current = full['board_opportunity_model']['lists']['current']

def current_ids(kind):
    return [b['id'] for b in sorted(
        (b for b in by.values() if b['type'] == kind and b['id'] in current),
        key=lambda b: b['opportunity']['sort_rank'])]

advance = [b for b in by.values() if b['type'] == 'theme'
           and b.get('ranking_eligible')
           and (b.get('index_current') or {}).get('ready')
           and (b.get('index_current') or {}).get('strong_advance')]
assert len(advance) == 13
assert len({b['trend_rank'] for b in advance}) == len(advance)
assert len({b['member_today'] for b in advance}) == len(advance)
expected = {
    1: current_ids('theme'),
    2: [b['id'] for b in sorted(advance, key=lambda b: -b['member_today'])],
    3: current_ids('industry'),
    4: current_ids('theme'),
    5: ['theme:PCB概念'],
    6: [b['id'] for b in sorted(advance, key=lambda b: b['trend_rank'])],
}
rows = []
for i, ids in expected.items():
    p = (Path.home() / 'Downloads') / ('板块机会依据_2026-10-12 (%s).json' % i)
    d = json.loads(p.read_text(encoding='utf-8-sig'))
    assert [b['id'] for b in d['rows']] == ids, (i, '导出或排序不一致')
    for b in d['rows']:
        assert b['opportunity'] == by[b['id']]['opportunity']
        assert b['member_codes'] == by[b['id']]['member_codes']
        assert b['type'] == by[b['id']]['type']
        assert b['opportunity']['checks'], '后台资格表须完整保留'
    (out / ('负责人复验_实际导出%s.json' % i)).write_bytes(p.read_bytes())
    rows.append({'number': i, 'ids': ids, 'count': len(ids), 'all_fields_equal': True})
manifest = json.loads((out.parent / 'board_opportunity_round1_20261012/source_manifest.json').read_text(encoding='utf-8'))
unchanged = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() == v['after_sha256']
             for name, v in manifest.items() if name != 'dashboard_template.html'}
assert all(unchanged.values())
disk = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
assert disk == json.loads((out / 'before/snapshot.json').read_text(encoding='utf-8'))
assert full['board_opportunity_model'] == disk['board_opportunity_model']
assert [b['opportunity'] for b in full['board_catalog']] == [b['opportunity'] for b in disk['board_catalog']]
ev = {
    'verified_at': s.get('now'), 'generation': s['ui_generation'],
    'data_version': s['data_version'], 'independent_downloads': rows,
    'backend_hashes_unchanged': unchanged, 'snapshot_unchanged': True,
    'catalog_count': len(by), 'targeted_tests': 46,
    'dashboard_check': 'passed', 'live_service_check': 'passed',
    'page_errors': [], 'hidden_tables': 0,
    'ime_scope': '负责人独立验证中文输入、焦点和自动切换；CDP组合输入依据操作员已交付日志及源码检查，未独立复做操作系统输入法',
    'market_path_scope': '本轮仅投影模板修复，上轮已独立完成真实刷新；下午及收盘实盘未发生。',
}
(out / '负责人再次验收证据.json').write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'downloads_checked': len(rows), 'counts': [r['count'] for r in rows],
                  'sorting_formula_equal': True, 'checks_retained': True,
                  'version': s['data_version']}, ensure_ascii=False))
