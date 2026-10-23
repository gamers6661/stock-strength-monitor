"""Frozen diagnostics and prospective evaluation. No fitting or trade-profit claims."""
import gzip
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import config
import stock_selection as S
import stock_selection_data as D
import stock_selection_rollout as rollout

REPORT=config.ROOT/'research/stock_selection_v3_fix2_20261021'
HORIZONS=(1,5,10,20)


def outcome(history,day,horizon,calendar):
    index=calendar.index(day)
    if index+horizon>=len(calendar):return None
    dates=calendar[index:index+horizon+1]
    lookup={b['date']:b for b in history}
    # Missing future trading dates are unknown, never shorter substitutes.
    if any(d not in lookup for d in dates):return None
    window=[lookup[d] for d in dates]
    modes={(b.get('price_basis'),b.get('price_basis_source')) for b in window}
    if len(modes)!=1 or not modes.issubset({('qfq',s) for s in S.intraday._QFQ_HISTORY_SOURCES}|{('raw',s) for s in S.intraday._RAW_HISTORY_SOURCES}):return None
    if not all(S.intraday._valid_historical_price_bar(b) for b in window):return None
    first=lookup[day]['close'];future=window[1:]
    return dict(return_pct=100*(future[-1]['close']/first-1),
        mae_pct=100*(min(b['low'] for b in future)/first-1),
        intraday_pullback=any(100*(b['high']-b['close'])/b['high']>=2 for b in future))


def summarize(rows):
    if not rows:return dict(observations=0,mean_excess=None)
    return dict(observations=len(rows),days=len({r['day'] for r in rows}),
        mean_excess=statistics.mean(r['excess_pct'] for r in rows),
        median_excess=statistics.median(r['excess_pct'] for r in rows),
        positive_excess_share=statistics.mean(r['excess_pct']>0 for r in rows),
        mean_mae=statistics.mean(r['mae_pct'] for r in rows),
        intraday_pullback_share=statistics.mean(r['intraday_pullback'] for r in rows))


def grouped(rows,key):
    groups=defaultdict(list)
    for row in rows:groups[row[key]].append(row)
    return {str(k):summarize(v) for k,v in groups.items()}


def replay():
    REPORT.mkdir(parents=True,exist_ok=True)
    freeze=rollout.load(REPORT/'freeze.json')
    if freeze['implementation_hash']!=S.IMPLEMENTATION_HASH:raise ValueError('implementation changed after freeze; freeze a new version before replay')
    started=time.monotonic()
    frozen_input=REPORT/'replay-inputs.json.gz'
    if frozen_input.exists():
        with gzip.open(frozen_input,'rt',encoding='utf8') as stream:bundle=json.load(stream)
        snap=bundle['source'];histories=bundle['histories'];calendar=bundle['calendar'];amounts=bundle['amounts'];funds=bundle['funds']
    else:
        snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
        master=S.read('security_master.json')
        snap=dict(snap,_security_master=master.get('stocks',{}),_universe_at=str(datetime.now().date()))
        histories,calendar=S.inputs(snap);amounts=D.load()
        import fund_history
        funds=fund_history.load()
        row_keys=('code','name','industry','industry_detail','board_type','price','open','high','low','last_close','change_pct',
            'quote_at','ts','amount_wan','volume_shou','price_basis','price_basis_source','last_close_semantics','last_close_precision_digits','limit_up','limit_down')
        source={k:snap.get(k) for k in ('quote_capture_at','generated_at','session','close_daily_verified_at','market_strength_close_input','_security_master','_universe_at')}
        source.update({k:[{field:r[field] for field in row_keys if field in r} for r in snap.get(k,[])] for k in ('stocks','coverage_catalog')})
        source['board_catalog']=[{k:b.get(k) for k in ('id','name','type','member_codes')} for b in snap.get('board_catalog',[])]
        bundle=dict(captured_at=str(datetime.now()),source=source,histories=histories,calendar=calendar,amounts=amounts,funds=funds,
            legacy_archives={p.stem.removeprefix('close-'):rollout.load(p) for p in (config.CACHE_DIR/'stock_activity_v21').glob('close-*.json')})
        with gzip.open(frozen_input,'wt',encoding='utf8',compresslevel=3) as stream:json.dump(bundle,stream,ensure_ascii=False,separators=(',',':'))
        snap=source
    state={};old_state={};days=[];observations=[];models={}
    base_engine=rollout.baseline(S.read('rollout.json'))
    last_ids=None;legacy_days=[]
    for day in calendar[-45:]:
        source=dict(snap,quote_capture_at=day+' 15:00:00',session='已收盘',
            close_daily_verified_at=day+' 16:00:00',_historical_replay=True,_fund_records=funds)
        model=S.build(source,histories,calendar,state,amounts,now=S.parse_at(day+' 16:00:00'))
        state=model.pop('_state');models[day]=model
        old=base_engine.build(source,histories,calendar,old_state,amounts,now=S.parse_at(day+' 16:00:00'))
        old_state=old.pop('_state')
        scored=[c for c in model['order'] if model['items'][c]['score'] is not None]
        selectors=dict(full_score=scored[:20],previous_v3_score=[c for c in old['order'] if old['items'][c]['score'] is not None][:20],
            return5=sorted(scored,key=lambda c:model['items'][c]['evidence']['returns']['5'],reverse=True)[:20])
        # Leave-one-dimension-out ranking: remaining fixed weights renormalized only in this research comparison.
        for removed in ('price','relative','volume'):
            weights={k:v for k,v in S.R['weights'].items() if k!=removed};total=sum(weights.values())
            selectors['without_'+removed]=sorted(scored,key=lambda c:(-sum(model['items'][c]['dimensions'][k]*v/total for k,v in weights.items()),c))[:20]
        amount_ok=model['coverage']['amount_complete']/max(len(scored),1)>=.8
        ids=set(rollout.selected(model)) if amount_ok else None
        selectors['qualified']=sorted(ids) if ids is not None else None
        selectors['qualified_board_supported']=[c for c in sorted(ids) if model['items'][c]['board']['label']=='板块支持'] if ids is not None else None
        selectors['qualified_fund_positive']=[c for c in sorted(ids) if model['items'][c]['fund']['available'] and model['items'][c]['fund']['main_net']>0] if ids is not None else None
        legacy=bundle['legacy_archives'].get(day,{})
        selectors['legacy_v21_archived']=sorted(c for c,x in legacy.get('items',{}).items() if x.get('eligible') and c in model['items']) if legacy.get('close_finalized') else None
        if selectors['legacy_v21_archived'] is not None:legacy_days.append(day)
        changes=None if ids is None or last_ids is None else dict(entries=len(ids-last_ids),exits=len(last_ids-ids),
            changed_share=len(ids^last_ids)/max(len(ids|last_ids),1))
        regime=('上涨截面' if model['items'][scored[0]]['evidence']['market_returns']['5']>0 else '下跌或持平截面') if scored else '未知'
        for h in HORIZONS:
            values={c:v for c in scored if (v:=outcome(histories[c],day,h,calendar)) is not None}
            if not values:continue
            reference=statistics.median(v['return_pct'] for v in values.values())
            for method,codes in selectors.items():
                if codes is None:continue
                for c in codes:
                    value=values.get(c)
                    if value is None:continue
                    x=model['items'][c];amount=x['evidence']['median_amount']
                    liquidity='未知' if amount is None else '<1亿元' if amount<1e8 else '1-5亿元' if amount<5e8 else '>=5亿元'
                    observations.append(dict(day=day,code=c,method=method,horizon=h,industry=x['board'].get('industry') or '未知',
                        regime=regime,liquidity=liquidity,excess_pct=value['return_pct']-reference,**value))
        days.append(dict(day=day,coverage=model['coverage'],qualified=None if ids is None else sorted(ids),changes=changes,
            unavailable_methods=[k for k,v in selectors.items() if v is None]))
        last_ids=ids
        print('replay',day,'scored',len(scored),'qualified',None if ids is None else len(ids),flush=True)
    events=[]
    for index,day in enumerate([d['day'] for d in days]):
        model=models[day];future_days=[d for d in models if d>day][:5]
        mature=len(future_days)==5
        for code,x in model['items'].items():
            if not x.get('eligible') or x['pattern'] not in ('突破启动','强势整理'):continue
            future=[next((b for b in histories[code] if b['date']==d),None) for d in future_days]
            if not mature or any(b is None for b in future):continue
            anchor=x.get('anchor');support=anchor.get('support') if anchor else None
            events.append(dict(day=day,code=code,pattern=x['pattern'],
                support_failed=any(b['close']<support for b in future) if support is not None else None,
                restarted=any(models[d]['items'][code]['pattern']=='再启动' for d in future_days)))
    event_stats={}
    for pattern in ('突破启动','强势整理'):
        rows=[e for e in events if e['pattern']==pattern]
        valid=[e for e in rows if e['support_failed'] is not None]
        event_stats[pattern]=dict(observations=len(rows),close_below_frozen_support_share=statistics.mean(e['support_failed'] for e in valid) if valid else None,
            restart_within5_share=statistics.mean(e['restarted'] for e in rows) if rows else None)
    qualified_days=[d for d in days if d['qualified'] is not None]
    reversals=0;eligible_pairs=0
    for i in range(1,len(days)-1):
        if any(days[k]['qualified'] is None for k in (i-1,i,i+1)):continue
        exited=set(days[i-1]['qualified'])-set(days[i]['qualified'])
        reversals+=len(exited&set(days[i+1]['qualified']));eligible_pairs+=len(exited)
    report=dict(version=S.VERSION,implementation_hash=S.IMPLEMENTATION_HASH,frozen_at=freeze['frozen_at'],rules=S.R,
        days=days,aggregate=[dict(method=m,horizon=h,**summarize([r for r in observations if r['method']==m and r['horizon']==h]))
            for m in sorted({r['method'] for r in observations}) for h in HORIZONS],
        groups={str(h):{key:grouped([r for r in observations if r['method']=='qualified' and r['horizon']==h],key) for key in ('industry','regime','liquidity')} for h in HORIZONS},
        events=event_stats,exit_then_next_day_reentry=dict(exits=eligible_pairs,reentries=reversals,share=reversals/eligible_pairs if eligible_pairs else None),
        legacy_v21_archive_days=legacy_days,qualified_days=len(qualified_days),
        chronological_diagnostic=dict(early=[d['day'] for d in days[:15]],purged=[d['day'] for d in days[15:35]],
            later=[d['day'] for d in days[35:]],max_horizon_isolation=20,
            independent_out_of_sample=False,reason='这些历史日期在初次回放中已被查看，不能重新命名为未知样本外'),
        market_cap_grouping=dict(status='不可追溯',reason='历史流通股本/市值未留档，禁止用今天市值回填历史；真实影子日起记录'),
        limitations=['当前证券池与分类有存活和分类偏差','旧V2.1只使用真实收盘档案，不用趋势分替代事件模型',
            '消融为评分排序消融；板块和资金比较独立筛选，不伪装主分因子',
            '准入组合金额覆盖不足日期为null，不当作零入选',
            '统计价格表现，未评估交易收益；未模拟T+1、涨跌停成交、费用和滑点',
            '时间切片仅诊断；真正样本外从规则冻结之后开始，未来窗口未成熟保持待观察'],
        segmented_aggregate={name:[dict(method=m,horizon=h,**summarize([r for r in observations if r['method']==m and r['horizon']==h and r['day'] in selected]))
            for m in sorted({r['method'] for r in observations}) for h in HORIZONS]
            for name,selected in (('early',{d['day'] for d in days[:15]}),('later',{d['day'] for d in days[35:]}))},
        input_archive=str(frozen_input),input_captured_at=bundle['captured_at'],seconds=round(time.monotonic()-started,3))
    rollout.save(REPORT/'replay.json',report)
    rollout.save(REPORT/'replay_observations.json',observations)
    print('saved',REPORT/'replay.json','seconds',report['seconds'],flush=True)


def archive_metadata(snap):
    day=str(snap.get('quote_capture_at',''))[:10];stocks={}
    for code,row in S.unique_rows(snap).items():
        at=S.parse_at(row.get('quote_at') or row.get('ts'));cap=row.get('float_mcap_yi')
        if at and str(at.date())==day and at.hour>=15 and S.number(cap) and cap>0:
            stocks[code]=dict(float_mcap_yi=cap,quote_at=str(at))
    rollout.save(rollout.root()/'shadow'/('metadata-'+day+'.json'),dict(day=day,observed_at=str(datetime.now()),stocks=stocks))


def freezes():
    return rollout.load(rollout.root()/'validation-registry.json')


def identity_valid(model,freeze):
    day=model.get('daily_at');captured=S.parse_at(model.get('captured_at'));source=S.parse_at(model.get('source_at'))
    frozen=S.parse_at(freeze.get('frozen_at'))
    return bool(model.get('close_finalized') and captured and source and frozen and
        day==model.get('day')==str(captured.date())==str(source.date()) and captured>=frozen and
        day>=str(frozen.date()) and model.get('implementation_hash')==freeze.get('implementation_hash'))


def readiness(model,freeze):
    if not identity_valid(model,freeze):return [dict(reason='日期、规则或收盘证明不匹配')]
    items=model.get('items') or {};coverage=model.get('coverage') or {};reasons=[]
    rules=freeze.get('rules') or S.R
    if not items or model.get('pool_count')!=len(items):reasons.append(dict(reason='股票池不完整'))
    if coverage.get('market',0)<rules['market_coverage']:reasons.append(dict(reason='可比日线覆盖不足'))
    if not coverage.get('daily') or coverage.get('amount_complete')!=coverage['daily']:
        reasons.append(dict(reason='可评分股票的真实成交额尚未全部补齐'))
    for code,x in items.items():
        if x.get('score') is None:
            if x.get('data_status') not in ('上市历史不足','停牌日已核验'):
                reasons.append(dict(code=code,reason='自身强度尚不能计算'))
            continue
        e=x.get('evidence') or {};live=x.get('intraday') or {}
        if e.get('amount_days')!=20 or not S.number(e.get('median_amount')):
            reasons.append(dict(code=code,reason='真实金额未齐'))
        if not live.get('available') or (live.get('completed_daily_proof') or {}).get('date')!=model['daily_at']:
            reasons.append(dict(code=code,reason='当天收盘报价尚未逐项核验'))
        if not isinstance(x.get('eligible'),bool):reasons.append(dict(code=code,reason='资格状态未知'))
    return reasons


def valid_forward_model(model,freeze):
    return not readiness(model,freeze)


def seal_decisions(registry):
    pending=[]
    for path in sorted(rollout.root().glob('close-*.json')):
        model=rollout.load(path);freeze=registry.get(model.get('implementation_hash'))
        if not freeze or not identity_valid(model,freeze):continue
        sealed=rollout.root()/'shadow'/('forward-signals-'+model['daily_at']+'-'+model['implementation_hash']+'.json')
        if sealed.exists():continue
        reasons=readiness(model,freeze)
        if reasons:
            pending.append(dict(day=model['daily_at'],version=model.get('version'),implementation_hash=model['implementation_hash'],
                status='data_pending',reasons=reasons,observed_at=model['captured_at']))
            continue
        keep={k:model[k] for k in ('day','daily_at','captured_at','source_at','implementation_hash','close_finalized','coverage','pool_count')}
        keep['version']=model.get('version')
        keep['items']={c:{k:x.get(k) for k in ('score','eligible','list_name','data_status','board','evidence','intraday')} for c,x in model['items'].items()}
        rollout.save(sealed,keep)
    models=[]
    for path in sorted((rollout.root()/'shadow').glob('forward-signals-*.json')):
        model=rollout.load(path);freeze=registry.get(model.get('implementation_hash'))
        if freeze and valid_forward_model(model,freeze):models.append(model)
    return models,pending


def forward_inputs(models,asof):
    """Read archived codes, including removed securities, without a rolling row limit."""
    import sqlite3
    if not models:return {},[]
    codes=sorted({c for m in models for c in m['items']});start=min(m['daily_at'] for m in models)
    con=sqlite3.connect('file:'+config.KLINE_DB.as_posix()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    try:
        columns='date,open,close,high,low,volume,amount,price_basis,price_basis_source'
        histories={c:[dict(r) for r in con.execute('SELECT '+columns+' FROM kline WHERE code=? AND date>=? AND date<=? ORDER BY date',(c,start,asof))] for c in codes}
    finally:con.close()
    from stock_selection_calendar import load_calendar
    calendar=load_calendar(start,asof)
    return histories,calendar


EVALUATION_VERSION='price-v3.5-calendar-20261022'


def result_path(model):
    return rollout.root()/'shadow'/('forward-results-'+model['daily_at']+'-'+model['implementation_hash']+'-'+EVALUATION_VERSION+'.json')


def evaluate_forward(models,histories,calendar,caches=None):
    """Previously mature results never disappear when a security leaves the pool."""
    caches=caches or {};signals=[];decisions=[];results=[]
    for model in models:
        day=model['daily_at'];key=(model['implementation_hash'],day);prior=caches.get(key,{})
        old={(r['code'],r['horizon']):r for r in prior.get('observations',[]) if r.get('status')=='mature'}
        universe=sorted(model['items']);ids=rollout.selected(model)
        metadata=rollout.load(rollout.root()/'shadow'/('metadata-'+day+'.json')).get('stocks',{})
        rows=[];benchmarks=prior.get('benchmarks',{}).copy()
        regime=next((x['evidence'].get('market_returns',{}).get('5') for x in model['items'].values() if x.get('score') is not None),None)
        regime='未知' if regime is None else '上涨截面' if regime>0 else '下跌或持平截面'
        for h in HORIZONS:
            todo=[c for c in ids if (c,h) not in old]
            values={c:v for c in universe if c in histories and day in calendar and (v:=outcome(histories[c],day,h,calendar)) is not None} if todo else {}
            coverage=len(values)/max(len(universe),1)
            base=statistics.median(v['return_pct'] for v in values.values()) if coverage>=.8 else None
            if todo:benchmarks[str(h)]=dict(universe=len(universe),valid=len(values),coverage=coverage,median_return=base)
            for code in ids:
                if (code,h) in old:rows.append(old[(code,h)]);continue
                value=values.get(code);x=model['items'][code];cap=metadata.get(code,{}).get('float_mcap_yi');amount=x['evidence']['median_amount']
                reason='calendar_missing' if day not in calendar else 'not_mature' if calendar.index(day)+h>=len(calendar) else 'price_data_missing_or_incomparable' if value is None else 'benchmark_incomplete' if base is None else None
                rows.append(dict(day=day,code=code,horizon=h,implementation_hash=model['implementation_hash'],
                    status='mature' if reason is None else 'pending',reason=reason,
                    industry=x['board'].get('industry') or '未知',regime=regime,
                    float_cap_group='未知' if cap is None else '<100亿元' if cap<100 else '100-500亿元' if cap<500 else '>=500亿元',
                    liquidity='<1亿元' if amount<1e8 else '1-5亿元' if amount<5e8 else '>=5亿元',
                    return_pct=value['return_pct'] if reason is None else None,mae_pct=value['mae_pct'] if reason is None else None,
                    intraday_pullback=value['intraday_pullback'] if reason is None else None,
                    excess_pct=value['return_pct']-base if reason is None else None,
                    evaluated_at=str(datetime.now())))
        record=dict(day=day,implementation_hash=model['implementation_hash'],evaluation_version=EVALUATION_VERSION,
            decision_at=model['captured_at'],selected_count=len(ids),universe=universe,benchmarks=benchmarks,observations=rows)
        results.append((model,record));signals.extend(rows)
        decisions.append(dict(day=day,implementation_hash=model['implementation_hash'],selected_count=len(ids),status='ready'))
    return signals,decisions,results


def forward(histories=None,calendar=None):
    from datetime import timedelta
    registry=freezes();models,pending=seal_decisions(registry)
    caches={(m['implementation_hash'],m['daily_at']):rollout.load(result_path(m)) for m in models}
    unresolved=[m for m in models if len({(r['code'],r['horizon']) for r in caches[(m['implementation_hash'],m['daily_at'])].get('observations',[]) if r.get('status')=='mature'})<len(rollout.selected(m))*len(HORIZONS)]
    if histories is None:
        now=datetime.now();cutoff=str(now.date() if now.hour>=16 else (now-timedelta(days=1)).date())
        histories,calendar=forward_inputs(unresolved,cutoff)
    signals,decisions,results=evaluate_forward(models,histories,calendar,caches)
    for model,result in results:rollout.save(result_path(model),result)
    mature=[r for r in signals if r['status']=='mature']
    groups={}
    for version in sorted({r['implementation_hash'] for r in mature}):
        groups[version]={str(h):{key:grouped([r for r in mature if r['implementation_hash']==version and r['horizon']==h],key)
            for key in ('industry','regime','liquidity','float_cap_group')} for h in HORIZONS}
    report=dict(asof=str(datetime.now()),version=S.VERSION,evaluation_version=EVALUATION_VERSION,effect_validated=False,
        mature=len(mature),awaiting=len(signals)-len(mature),missing=sum(r.get('reason') not in (None,'not_mature') for r in signals),
        signal_days=len(decisions),decisions=decisions,pending_decisions=pending,observations=signals,groups=groups,
        note='未齐的决策不封存为零信号；真实零信号日明确保留；成熟结果不因滚动历史或移出股票池而消失。')
    rollout.save(rollout.root()/'forward_validation.json',report)
    return report


if __name__=='__main__':
    import sys
    if '--forward' in sys.argv:print(json.dumps({k:v for k,v in forward().items() if k not in ('observations','groups')},ensure_ascii=False))
    else:replay()
