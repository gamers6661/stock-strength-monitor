import sys,json,gzip,time,copy,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import radar_opportunity as ro
OUT=Path(__file__).resolve().parent
with gzip.open(OUT/'frozen_inputs.json.gz','rt',encoding='utf-8') as f:data=json.load(f)
old=data['snapshot'];new=copy.deepcopy(old);start=time.perf_counter()
model=ro.build(new,data['quotes'],data['pool'],data['contexts'],data['histories'],data['calendar'],state={},persist=False)
elapsed=time.perf_counter()-start;ro.validate(new)
clean=copy.deepcopy(new);clean.pop('radar_opportunity')
for row in clean['stocks']+clean['coverage_catalog']:row.pop('radar_opportunity')
assert clean==old
with gzip.open(OUT/'final_frozen_result.json.gz','wb') as f:f.write(json.dumps(new,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
report=dict(version=ro.VERSION,implementation_hash=ro.IMPLEMENTATION_HASH,old_fields_identical=True,added_compute_seconds=elapsed,
            counts=model['counts'],lists=model['lists'],quote_capture_at=old['quote_capture_at'],generated_at=old['generated_at'],
            input_sha256=hashlib.sha256((OUT/'frozen_inputs.json.gz').read_bytes()).hexdigest())
(OUT/'final_frozen_compare.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
