"""核对后台源码与快照未改，模板里的非展示函数未改。"""
import hashlib
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
before=json.loads((OUT/'backend_before.json').read_text(encoding='utf-8-sig'))
for item in before:
    path=Path(item['Path']);assert hashlib.sha256(path.read_bytes()).hexdigest().upper()==item['Hash'],path.name
frozen=json.loads((OUT/'snapshot_before.json').read_text(encoding='utf-8-sig'))
assert hashlib.sha256(Path(frozen['Path']).read_bytes()).hexdigest().upper()==frozen['Hash'],'数据快照发生改变'
def functions(text):
    matches=list(re.finditer(r'^function (\w+)\([^\n]*',text,re.M));out={}
    for i,m in enumerate(matches):
        piece=text[m.start():matches[i+1].start() if i+1<len(matches) else len(text)]
        # 两函数之间的注释不参与比较；末尾初始化独立核验。
        piece=piece[:piece.rfind('\n}')+2]
        out[m.group(1)]=piece.strip()
    return out
old=(OUT/'dashboard_template.before.html').read_text(encoding='utf-8')
new=(ROOT/'dashboard_template.html').read_text(encoding='utf-8')
a,b=functions(old),functions(new)
changed=[n for n in a if a[n]!=b.get(n)]
allowed={'renderAttackMonitor','renderConsolidationMonitor','sessionContextDetail','structureDetail','showStock','init'}
assert set(changed)<=allowed,changed
normalized_init=re.sub(r'^  initUiNotes\(\);\n|^  document.getElementById\(\'ui-attack-rules\'\).innerHTML=.*\n','',b['init'],flags=re.M)
assert normalized_init==a['init'],'初始化出现注释以外的修改'
assert a['exportCSV']==b['exportCSV'],'CSV导出规则改变'
result=dict(backend_files_unchanged=len(before),snapshot_unchanged=True,changed_functions=changed,
    added_display_helpers=[n for n in b if n not in a],unchanged_functions=len(a)-len(changed))
(OUT/'scope.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
