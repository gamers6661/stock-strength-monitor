import json,urllib.request,subprocess
url='http://127.0.0.1:8848/__status'
with urllib.request.urlopen(url,timeout=4) as res: data=json.load(res)
print('status',json.dumps({k:data.get(k) for k in ('pid','phase','last_scan_ok','port','error','time')},ensure_ascii=False))
pid=data.get('pid')
if pid:
 cmd=f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" | Select-Object -ExpandProperty CommandLine'
 p=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,text=True,encoding='utf-8',errors='replace')
 print('process',repr(p.stdout.strip()),'exit',p.returncode)
