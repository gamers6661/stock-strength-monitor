"""保存本轮之前的一期源码和冻结输入；备份不位于模块搜索路径。"""
from pathlib import Path
import gzip
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BACKUP = ROOT / 'backups' / 'latest_before_wyckoff_round1'

def run():
    BACKUP.mkdir(parents=True, exist_ok=True)
    archive = BACKUP / 'source.zip'
    if archive.exists():
        raise RuntimeError('本期备份已经存在，禁止覆盖')
    files = [p for p in ROOT.iterdir() if p.is_file() and
             (p.suffix in ('.py', '.pyw', '.bat', '.ps1', '.vbs', '.md', '.txt') or
              p.name == 'dashboard_template.html')]
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)
    raw = (ROOT / 'cache/snapshot.json').read_bytes()
    with gzip.open(BACKUP / 'snapshot.json.gz', 'wb') as f:
        f.write(raw)
    snapshot = json.loads(raw)
    rows = snapshot.get('stocks', []) + snapshot.get('coverage_catalog', [])
    keys = ('stock_strength_score', 'stock_strength_percentile', 'stock_strength_parts',
            'trend_online', 'trend_tier', 'daily_attack_tier', 'live_attack_score',
            'live_attack_price_score', 'live_attack_tier', 'attack_watch_candidate')
    baseline = {r['code']: {k:r.get(k) for k in keys} for r in rows}
    (OUT / 'baseline.json').write_text(json.dumps(baseline, ensure_ascii=False), encoding='utf-8')
    (BACKUP / 'README.md').write_text(
        '# 本轮修改前最近一期备份\n\n'
        'source.zip 保存修改前的运行源码、模板、测试和入口。snapshot.json.gz 保存当时快照。\n'
        '备份只用于恢复，不参与导入、扫描或新版结构留档。恢复需停止服务后解压源码并重新生成看板。\n'
        f'快照时间：{snapshot.get("generated_at")}\n', encoding='utf-8')
    print(json.dumps({'backup':str(BACKUP), 'source_files':len(files),
                      'snapshot_at':snapshot.get('generated_at'), 'baseline_rows':len(baseline)}, ensure_ascii=False))

if __name__ == '__main__':
    run()
