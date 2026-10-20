"""Controlled one-service deployment. Validates PID, uses original runtime and preserves cache."""
import json,os,signal,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(r'D:\股票强势监测')
def status(timeout=3):
    with urllib.request.urlopen('http://127.0.0.1:8848/__status',timeout=timeout) as res:return json.load(res)
before=status()
pid=before.get('pid')
assert isinstance(pid,int) and pid>0 and before.get('phase')=='ready',before
cmd=subprocess.run(['powershell','-NoProfile','-Command',f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" | Select-Object -ExpandProperty CommandLine'],capture_output=True).stdout.decode('gbk',errors='replace').strip()
assert '股票强势监测' in cmd and 'serve.py' in cmd and 'pythonw.exe' in cmd,repr(cmd)
pythonw=Path(cmd.split('"')[1])
assert pythonw.exists(),str(pythonw)
print('OLD_VERIFIED',pid,pythonw,flush=True)
os.kill(pid,signal.SIGTERM)
time.sleep(1)
flags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
subprocess.Popen([str(pythonw),str(ROOT/'serve.py'),'--no-browser'],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,close_fds=True)
print('RESTART_REQUESTED',flush=True)
last=None
for i in range(50):
    try:
        s=status()
        if s.get('pid')!=pid and s.get('phase')=='ready':
            print('NEW_READY',json.dumps({k:s.get(k) for k in ('pid','phase','last_scan_ok','time')},ensure_ascii=False),flush=True)
            break
        last=(s.get('pid'),s.get('phase'))
    except Exception as e:last=str(e)
    time.sleep(1)
else:
    raise RuntimeError('Service not ready after restart: '+repr(last))
target=ROOT/'cache'/'stock_activity_v21'/'latest.json'
for i in range(50):
    try:
        result=json.loads(target.read_text(encoding='utf-8'))
        if result.get('version')=='个股主动强度V2.1-20261020.4':
            print('NEW_MODEL',result['version'],result.get('source_at'),result.get('counts'),flush=True)
            break
    except (OSError,ValueError):pass
    time.sleep(1)
else:
    print('PENDING_MODEL_PUBLICATION',flush=True)
