"""Same-input shadow comparison; promotion is a technical gate, not a profit claim."""
import copy
import hashlib
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path

import config

_BASELINE=None


def root():
    return config.CACHE_DIR/'stock_selection_v3'


def load(path,default=None):
    try:return json.loads(path.read_text(encoding='utf8'))
    except FileNotFoundError:return {} if default is None else default


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    config.atomic_write_text(path,json.dumps(data,ensure_ascii=False,separators=(',',':')))


def candidate_state(production):
    return load(root()/'candidate-state.json') if load(root()/'rollout.json').get('stage')=='shadow' else production


def baseline(policy):
    global _BASELINE
    if _BASELINE is None or str(Path(_BASELINE.__file__).parent)!=str(Path(policy['baseline'])):
        folder=Path(policy['baseline'])
        def module(name,file):
            spec=importlib.util.spec_from_file_location(name,folder/file)
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
        rules=module('_selection_baseline_rules','stock_selection_rules.py')
        engine=module('_selection_baseline_engine','stock_selection.py')
        engine.R=rules.RULES;engine.VERSION=rules.VERSION
        engine.IMPLEMENTATION_HASH=load(folder/'cache/stock_selection_v3/latest.json')['implementation_hash']
        _BASELINE=engine
    return _BASELINE


def selected(model):
    return sorted(c for c,x in model['items'].items() if x.get('eligible'))


def project(candidate,source,histories,calendar,records,frames,now,production_previous):
    policy=load(root()/'rollout.json')
    if not policy:return candidate
    if policy.get('stage') == 'live':
        # Technical comparison finished at promotion. Keep its evidence, without
        # rebuilding the retired model on every production quote.
        last = load(root()/'shadow-last.json')
        candidate['rollout'] = dict(stage='live', candidate_version=candidate['version'],
            comparison_source_at=last.get('source_at'), comparison_active=False,
            effectiveness_validated=False, legacy_error=None)
        return candidate
    started=time.monotonic()
    # Separate candidate and legacy state; never replace the legacy production archive.
    save(root()/'candidate-state.json',candidate['_state'])
    save(root()/'candidate-latest.json',{k:v for k,v in candidate.items() if k!='_state'})
    legacy_error=None
    try:
        import stock_activity
        old_previous=load(root()/'shadow-v21-state.json')
        if not old_previous:old_previous=copy.deepcopy(stock_activity.load_state())
        legacy=stock_activity.build(copy.deepcopy(source),histories,calendar,frames=frames,
            previous=old_previous,detected_at=str(now))
        save(root()/'shadow-v21-state.json',legacy.pop('_state'))
        save(root()/'shadow-v21-latest.json',legacy)
    except Exception as exc:
        legacy_error=type(exc).__name__+': '+str(exc);legacy=dict(items={},version='V2.1',error=legacy_error)
    if policy['stage']=='shadow':
        published=baseline(policy).build(source,histories,calendar,production_previous,records,frames,now=now)
    else:published=candidate
    input_rows=[]
    import stock_selection as S
    for code,row in sorted(S.unique_rows(source).items()):
        input_rows.append([code]+[row.get(k) for k in ('quote_at','ts','price','open','high','low','last_close','amount_wan','volume_shou')])
    input_hash=hashlib.sha256(json.dumps(input_rows,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:20]
    candidate_ids=selected(candidate);production_ids=selected(published);legacy_ids=selected(legacy)
    at=S.parse_at(candidate['source_at'])
    record=dict(observed_at=str(datetime.now()),source_at=candidate['source_at'],daily_at=candidate['daily_at'],
        input_hash=input_hash,stage=policy['stage'],candidate_version=candidate['version'],
        candidate_hash=candidate['implementation_hash'],production_version=published['version'],
        legacy_version=legacy['version'],candidate_ids=candidate_ids,production_ids=production_ids,legacy_ids=legacy_ids,
        added=sorted(set(candidate_ids)-set(production_ids)),removed=sorted(set(production_ids)-set(candidate_ids)),
        coverage=candidate['coverage'],pending_share=candidate['counts']['pending']/max(candidate['pool_count'],1),
        same_input=True,legacy_error=legacy_error,comparison_seconds=round(time.monotonic()-started,3),
        quote_age_seconds=round((datetime.now()-at).total_seconds(),3) if at else None)
    log=root()/'shadow'/('observations-'+str(now.date())+'.jsonl')
    last=load(root()/'shadow-last.json')
    if last.get('source_at')!=record['source_at'] or last.get('candidate_hash')!=record['candidate_hash']:
        log.parent.mkdir(parents=True,exist_ok=True)
        with log.open('a',encoding='utf8') as stream:stream.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
        save(root()/'shadow-last.json',record)
    published['rollout']=dict(stage=policy['stage'],candidate_version=candidate['version'],comparison_source_at=record['source_at'],
        effectiveness_validated=False,legacy_error=legacy_error)
    return published


def accept():
    """Promote only after three distinct real source clocks span four minutes."""
    import stock_activity
    import stock_selection as S
    with stock_activity.projection_owner():
        policy=load(root()/'rollout.json')
        if policy.get('stage')!='shadow':raise ValueError('not in shadow stage')
        records=[]
        for path in sorted((root()/'shadow').glob('observations-*.jsonl')):
            for line in path.read_text(encoding='utf8').splitlines():
                row=json.loads(line)
                if row['candidate_hash']==S.IMPLEMENTATION_HASH and row['observed_at']>=policy['started_at']:records.append(row)
        distinct={r['source_at']:r for r in records};tail=sorted(distinct.values(),key=lambda r:r['source_at'])[-3:]
        gate=policy['technical_acceptance']
        if len(tail)<gate['min_distinct_source_samples']:raise ValueError('insufficient distinct real quotes')
        span=(S.parse_at(tail[-1]['source_at'])-S.parse_at(tail[0]['source_at'])).total_seconds()
        if span<gate['min_source_span_seconds']:raise ValueError('source-clock span below four minutes')
        if any(r['legacy_error'] or not r['same_input'] or r['coverage']['market']<gate['min_daily_coverage']
               or r['quote_age_seconds'] is None or not -60<=r['quote_age_seconds']<=S.R['max_quote_age_seconds'] for r in tail):
            raise ValueError('shadow technical gates failed')
        candidate=load(root()/'candidate-latest.json')
        if candidate['implementation_hash']!=S.IMPLEMENTATION_HASH:raise ValueError('candidate changed after validation')
        save(root()/'state.json',load(root()/'candidate-state.json'))
        save(root()/'latest.json',candidate)
        policy.update(stage='live',promoted_at=str(datetime.now()),technical_evidence=dict(samples=len(tail),source_span_seconds=span,
            input_hashes=[r['input_hash'] for r in tail]),effectiveness_validated=False)
        save(root()/'rollout.json',policy)
        return policy


if __name__=='__main__':
    import sys
    if '--accept' in sys.argv:print(json.dumps(accept(),ensure_ascii=False,indent=2))
    else:print(json.dumps(load(root()/'rollout.json'),ensure_ascii=False,indent=2))
