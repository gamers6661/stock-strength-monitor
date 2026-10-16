import importlib.util,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import ui_payload
p=Path(__file__).parent
spec=importlib.util.spec_from_file_location('payload_baseline',p/'baseline/ui_payload.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
full=json.loads((p/'frozen_full.json').read_text('utf8'))
template='var DATA = /*__DATA__*/null;'
out={}
for label,mod in [('before',old),('after',ui_payload)]:
    page=p/label/'dashboard.html';page.parent.mkdir(exist_ok=True)
    start=time.perf_counter();packet,token=mod.prepare(full,template,page)
    elapsed=time.perf_counter()-start
    summary=mod.unpack(packet)
    restored=mod.full(token,page)
    for group in ('stocks','coverage_catalog'):
        assert [r['market_strength'] for r in restored[group]]==[r['market_strength'] for r in full[group]]
    assert restored['market_strength']==full['market_strength']
    out[label]=dict(seconds=elapsed,packet_bytes=len(mod.dumps(packet).encode()),
                    database_bytes=mod.db_path(token,page).stat().st_size,token=token)
    for code in ('601811','001368','605287'):
        expected=next(r for r in full['stocks'] if r['code']==code)
        assert mod.detail(token,'stock',code,page)['market_strength']==expected['market_strength']
    print(label,out[label],flush=True)
    del restored,summary,packet
(p/'payload_comparison.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf8')
