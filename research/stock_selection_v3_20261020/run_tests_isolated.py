"""测试锁和临时文件均与D盘生产缓存隔离。"""
import os,sys,tempfile,json,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root));os.chdir(root)
os.environ.update(TEMP='D:/Temp/stock-monitor',TMP='D:/Temp/stock-monitor',PATH='D:/_tools/stock-monitor;'+os.environ['PATH']);tempfile.tempdir=None
import config
from unittest.mock import patch
out=Path(__file__).with_name('tests_final.txt')
d=tempfile.mkdtemp(prefix='stock-tests-',dir='D:/Temp/stock-monitor')
with patch.object(config,'CACHE_DIR',Path(d)),out.open('w',encoding='utf8') as log:
    suite=unittest.defaultTestLoader.discover(str(root),pattern='test_*.py')
    r=unittest.TextTestRunner(stream=log,verbosity=1).run(suite)
    result=dict(tests=r.testsRun,failures=len(r.failures),errors=len(r.errors),ok=r.wasSuccessful())
    print(json.dumps(result),flush=True)
    Path(__file__).with_name('tests_final.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print('测试缓存目录（收尾移入回收站）:',d)
sys.exit(0 if r.wasSuccessful() else 1)
