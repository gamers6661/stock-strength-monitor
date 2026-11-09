"""Reproduce one frozen-input comparison; never write production state."""
from pathlib import Path
import copy,gzip,hashlib,importlib.util,json,sys,time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import stock_selection as candidate
HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def main():
    assert not (HERE/'comparison.json').exists(),'Preserve original comparison evidence'
    frozen=json.loads(gzip.decompress((HERE/'frozen-inputs.json.gz').read_bytes()))
    original=load('_quality_baseline',HERE/'baseline/stock_selection.py')
    rules=load('_quality_baseline_rules',HERE/'baseline/stock_selection_rules.py')
    original.R=rules.RULES;original.VERSION=rules.VERSION
    models={}
    for label,engine in [('before',original),('after',candidate)]:
        start=time.monotonic()
        models[label]=engine.build(copy.deepcopy(frozen['source']),frozen['histories'],frozen['calendar'],
            previous=copy.deepcopy(frozen['previous']),amount_records=frozen['records'],
            now=engine.parse_at(frozen['now']))
        (HERE/(label+'-model.json.gz')).write_bytes(gzip.compress(json.dumps(models[label],ensure_ascii=False).encode(),compresslevel=1))
        print(label,'seconds',round(time.monotonic()-start,2),flush=True)
    before,after=models['before'],models['after'];changes=[]
    for code,a in before['items'].items():
        b=after['items'][code]
        changes.append(dict(code=code,name=b['name'],before=a['score'],after=b['score'],
            before_rank=a['rank'],after_rank=b['rank'],eligible_before=a['eligible'],eligible_after=b['eligible'],
            state_before=a['intraday']['state'],state_after=b['intraday']['state'],
            delta=round(b['score']-a['score'],2) if a['score'] is not None and b['score'] is not None else None))
    report=dict(generation=frozen['generation'],source_at=frozen['source']['quote_capture_at'],
        frozen_input_sha256=hashlib.sha256((HERE/'frozen-inputs.json.gz').read_bytes()).hexdigest(),
        candidate_hash=candidate.IMPLEMENTATION_HASH,counts_before=before['counts'],counts_after=after['counts'],
        coverage_before=before['coverage'],coverage_after=after['coverage'],changes=changes)
    (HERE/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='changes'},ensure_ascii=False),flush=True)
    for code in ('000058','601086'):
        x=after['items'][code]
        print(json.dumps(dict(change=next(r for r in changes if r['code']==code),quality=x['evidence'].get('quality'),dimensions=x['dimensions']),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
