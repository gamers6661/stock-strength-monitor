"""检查真实浏览器导出、清理结果、备份完整性及运行版本，生成验收证据。"""
import csv
import json
from pathlib import Path
import sys
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import wyckoff_structure as w

def run():
    out = Path(__file__).resolve().parent
    baseline = json.loads((out/'baseline.json').read_text(encoding='utf-8'))
    with (ROOT/'output/playwright/wyckoff-round1-all.csv').open(encoding='utf-8-sig', newline='') as f:
        records = list(csv.reader(f))
    header = records[0]
    assert len(header) == len(set(header)), 'CSV列名重复'
    assert all(len(r) == len(header) for r in records[1:]), 'CSV行列错位'
    rows = [dict(zip(header, r)) for r in records[1:]]
    assert len(rows) == len(baseline) and {r['代码'] for r in rows} == set(baseline), '全池导出名单遗漏或重复'
    saved = w.load_state()
    assert saved['version'] == w.VERSION
    structured = [r for r in rows if r['量价结构版本'] == w.VERSION]
    for r in structured:
        cycle = saved['cycles'][r['代码']]
        assert r['固定周期编号'] == cycle['cycle_id']
        for column, key in [('原平台上沿','platform_high'),('原平台下沿','platform_low'),
                            ('固定ATR20','atr0'),('量能参考','volume0')]:
            assert float(r[column]) == cycle[key], (r['代码'], column)
        assert r['结构证据截至'] == cycle['last_processed_asof']
    cleanup = json.loads((out/'cleanup_manifest.json').read_text(encoding='utf-8-sig'))
    assert all(not (ROOT/r['path']).exists() for r in cleanup['deleted'])
    backup = ROOT/cleanup['retained_backup']
    with zipfile.ZipFile(backup/'source.zip') as archive:
        assert archive.testzip() is None, '备份压缩包损坏'
        assert {'scoring.py','config.py','dashboard_template.html','serve.py'}.issubset(archive.namelist())
        changes = [name for name in archive.namelist()
                   if (name.endswith('.py') or name == 'dashboard_template.html')
                   and (ROOT/name).exists() and archive.read(name) != (ROOT/name).read_bytes()]
    assert (backup/'snapshot.json.gz').exists()
    for protected in ('cache/market.db','cache/stock_strength_daily/v6','cache/close_strong_attack_v6',
                      'research/rules_20260929/frozen_source','research/price_basis_20260930/baseline_round2'):
        assert (ROOT/protected).exists(), protected
    assert Path(w.__file__).resolve() == ROOT/'wyckoff_structure.py'
    with urlopen('http://127.0.0.1:8848/__status', timeout=10) as f:
        status = json.load(f)
    assert status['phase'] == 'ready' and status['last_publish_ok'] is True
    assert status['code_structure_version'] == status['snapshot_structure_version'] == w.VERSION
    evidence = dict(service=status, csv=dict(rows=len(rows), columns=len(header),
                    structured_rows=len(structured), all_codes_match_baseline=True,
                    frozen_platform_atr_volume_match_saved_cycles=True),
                    cleanup=dict(targets=len(cleanup['deleted']),
                    files=sum(r['files'] for r in cleanup['deleted']),
                    bytes=sum(r['bytes'] for r in cleanup['deleted']), all_targets_absent=True),
                    backup=dict(path=str(backup), source_zip_integrity=True),
                    changed_runtime_files=changes, new_runtime_files=['wyckoff_structure.py'],
                    browser_detail='output/playwright/wyckoff-round1-detail.png')
    (out/'final_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k!='service'},ensure_ascii=False))

if __name__ == '__main__':
    run()
