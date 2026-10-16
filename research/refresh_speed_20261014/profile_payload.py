import cProfile,io,json,pstats,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import ui_payload
root=Path(__file__).parent
started=time.perf_counter();token=ui_payload.active_generation();full=ui_payload.full(token)
print('loaded',round(time.perf_counter()-started,3),flush=True)
(root/'frozen_full.json').write_text(ui_payload.dumps(full),'utf8')
sizes=sorted(((k,len(ui_payload.dumps(v).encode())) for k,v in full.items()),key=lambda x:-x[1])
started=time.perf_counter();summary=ui_payload.summary(full,token)
summary_seconds=time.perf_counter()-started
ssizes=sorted(((k,len(ui_payload.dumps(v).encode())) for k,v in summary.items()),key=lambda x:-x[1])
prof=cProfile.Profile();started=time.perf_counter();prof.enable();packet=ui_payload.pack(summary);prof.disable()
pack_seconds=time.perf_counter()-started
buf=io.StringIO();pstats.Stats(prof,stream=buf).sort_stats('cumulative').print_stats(28)
(root/'pack_profile.txt').write_text(buf.getvalue(),'utf8')
out=dict(token=token,full_bytes=sum(n for _,n in sizes),full_largest=sizes[:15],summary_largest=ssizes[:15],
         summary_seconds=summary_seconds,pack_profiled_seconds=pack_seconds,packet_bytes=len(ui_payload.dumps(packet).encode()))
(root/'payload_profile.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(out,ensure_ascii=False),flush=True)
