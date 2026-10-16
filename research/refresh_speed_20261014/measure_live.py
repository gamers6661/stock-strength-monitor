"""Observe two real publications and their genuine source clocks."""
import json,time
from pathlib import Path
from urllib.request import Request,urlopen
p=Path(__file__).parent
base='http://127.0.0.1:8848'
seen=set();records=[];triggered=False;deadline=time.monotonic()+540
while time.monotonic()<deadline:
    try:
        status=json.loads(urlopen(base+'/__status',timeout=10).read())
        if status.get('refresh_interval_seconds')!=120:
            time.sleep(3);continue
        if not triggered and status['phase']=='ready' and not status['scan_active']:
            reply=json.loads(urlopen(Request(base+'/__refresh',data=b''),timeout=10).read())
            print('refresh requested',reply,flush=True);triggered=True
        perf=status.get('last_pipeline_performance') or {}
        at=perf.get('published_at')
        if at and at not in seen:
            seen.add(at);records.append(dict(pid=status['pid'],interval=status['refresh_interval_seconds'],ui_generation=status['ui_generation'],performance=perf))
            (p/'live_measurements.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf8')
            print(json.dumps(records[-1],ensure_ascii=False),flush=True)
            if len(records)>=2:break
    except Exception as error:
        print(type(error).__name__,str(error)[:120],flush=True)
    time.sleep(3)
else:raise SystemExit('Two live publications were not observed within the measurement window')
