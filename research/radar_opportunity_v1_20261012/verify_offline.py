import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,radar_opportunity as ro
OUT=Path(__file__).resolve().parent
def hashes():
    files=list(ro.directory().glob('*.jsonl'))+[ro.directory()/'state.json',config.SNAPSHOT_JSON]
    return {str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.exists()}
before=hashes();r=subprocess.run([sys.executable,'-B','-X','utf8','make_dashboard.py'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
(OUT/'offline_build_log.txt').write_text(r.stdout+r.stderr,encoding='utf-8');assert r.returncode==0
after=hashes();assert before==after,'离线生成改动了快照、事件或真实逐轮记录'
(OUT/'offline_projection_check.json').write_text(json.dumps(dict(all_unchanged=True,before=before,after=after),ensure_ascii=False,indent=2),encoding='utf-8')
print('离线生成前后：快照、事件状态、逐轮记录、发布日志哈希全部一致')
