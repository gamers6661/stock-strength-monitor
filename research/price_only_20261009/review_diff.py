from pathlib import Path
import difflib

root=Path.cwd()
backup=root/'research'/'price_only_20261009'
files=[p.name for p in backup.iterdir() if p.suffix in ('.py','.html') and (root/p.name).exists()]
diff=[]
for filename in sorted(files):
    before=(backup/filename).read_text(encoding='utf-8').splitlines(True)
    after=(root/filename).read_text(encoding='utf-8').splitlines(True)
    diff.extend(difflib.unified_diff(before,after,fromfile=filename+' before',tofile=filename+' after'))
for filename in ('price_only.py','test_price_only.py'):
    after=(root/filename).read_text(encoding='utf-8').splitlines(True)
    diff.extend(difflib.unified_diff([],after,fromfile='/dev/null',tofile=filename))
(backup/'changes.diff').write_text(''.join(diff),encoding='utf-8')
print('已整理变更差异',len(diff),'行')
