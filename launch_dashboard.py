"""本地看板独立启动入口，关闭编辑器不会结束服务。"""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
RUNTIME=Path('D:/_tools/stock-monitor/python/pythonw.exe')


def alive():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8848/__ping',timeout=2) as response:
            return response.status==200 and b'pong' in response.read()
    except Exception:return False


def detached(script):
    (ROOT/'logs').mkdir(exist_ok=True)
    env=dict(os.environ,PYTHONUTF8='1',TEMP='D:/Temp/stock-monitor',TMP='D:/Temp/stock-monitor')
    env['PATH']=str(RUNTIME.parent.parent)+os.pathsep+env.get('PATH','')
    Path(env['TEMP']).mkdir(parents=True,exist_ok=True)
    with (ROOT/'logs/launcher.log').open('ab') as log:
        return subprocess.Popen([str(RUNTIME),'-X','utf8',str(ROOT/script),'--no-browser'],cwd=ROOT,
            env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,
            creationflags=0x00000008|0x00000200 if os.name=='nt' else 0)


def main():
    if not RUNTIME.is_file():raise RuntimeError('D盘独立Python环境不存在：'+str(RUNTIME))
    stop=ROOT/'cache/serve.stop'
    if stop.exists():
        # 保留上一次人工停止记录，解除停止状态。
        import datetime
        stop.rename(stop.with_name('serve.stop.'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')))
    detached('watch_service.py')
    if not alive():detached('serve.py')
    for _ in range(60):
        if alive():
            if '--silent' not in sys.argv and '/silent' not in sys.argv and os.environ.get('SKIP_OPEN')!='1':
                webbrowser.open('http://127.0.0.1:8848/dashboard.html')
            return 0
        time.sleep(1)
    raise RuntimeError('服务未就绪，请查看 logs/serve.log 与 logs/launcher.log')


if __name__=='__main__':sys.exit(main())
