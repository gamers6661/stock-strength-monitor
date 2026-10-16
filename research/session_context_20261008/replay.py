"""回放今天留存的真实竞价原始输入，不写生产快照或历史。"""
from collections import Counter
import copy
from datetime import datetime
import gzip
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import scoring
import strength
import stock_strength
import fund_confirmation
import history_reference
import intraday
import session_context
import wyckoff_structure

def run():
    out=Path(__file__).parent
    base=json.loads(gzip.open(ROOT/'backups/latest_before_session_context/snapshot.json.gz','rt',encoding='utf-8').read())
    pool=json.loads(config.POOL_CACHE.read_text(encoding='utf-8'))
    series=scoring.formal_histories(list(pool))
    asof=base['strength_model']['asof']
    calendar=strength.trading_calendar({c:[b for b in bs if b['date']<=asof] for c,bs in series.items()})
    result=[]
    inputs=[]
    with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions/2026-10-08.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            r=json.loads(line)
            if r['session'] in ('集合竞价','竞价结束') and r['boundary'] in ('auction_start','auction_mid','auction_final'):inputs.append(r)
    completed=set()
    for acquisition in inputs:
        if acquisition['boundary'] in completed:continue
        at=datetime.fromisoformat(acquisition['captured_at'])
        q={r[0]:dict(zip(acquisition['fields'][1:],r[1:])) for r in acquisition['rows']}
        # 前一完成日日线字段可用于历史回放；删除当天未来盘中状态及之后创建的结构。
        prior=copy.deepcopy(base)
        prior.pop('boundary_prices',None)
        for row in prior['stocks']+prior.get('coverage_catalog',[]):
            for key in ('wyckoff_structure','trend_consolidation','intraday_path','auction_observation','session_context'):
                row.pop(key,None)
        prior['trend_consolidation']={};prior['wyckoff_structure']={}
        class Clock:
            @staticmethod
            def now():return at
        with patch.object(scoring,'datetime',Clock),patch.object(scoring.df,'build_pool',return_value=pool),\
             patch.object(scoring.df,'realtime_quotes',return_value=q),patch.object(scoring,'formal_histories',return_value=series),\
             patch.object(intraday.intraday_path,'save_acquisition'),patch.object(wyckoff_structure,'load_state',return_value={'version':wyckoff_structure.VERSION,'cycles':{},'archived_cycles':[]}),\
             patch.object(config,'atomic_write_text'),patch.object(scoring,'append_history'):
            try:replay=scoring._auction_snapshot(prior,'quick',at,boundary=acquisition.get('boundary'))
            except scoring.DataNotReady as exc:
                result.append(dict(captured_at=acquisition['captured_at'],boundary=acquisition['boundary'],
                                   retry_reason=str(exc),status='未发布竞价末价；源尚未更新，等待重试'))
                continue
        completed.add(acquisition['boundary'])
        ctx=replay['session_context'];assert ctx['price_judged_count']>0
        assert all(not r['current_strong_candidate'] for r in replay['stocks']+replay.get('coverage_catalog',[]))
        rows=replay['stocks']+replay.get('coverage_catalog',[])
        stock_strength.attach_history(replay['stocks'],calendar[-2],calendar[-6])
        fund_confirmation.attach(rows,calendar,fetch=False)
        info=dict(captured_at=acquisition['captured_at'],boundary=acquisition['boundary'],quotes=len(q),
                  price_judged=ctx['price_judged_count'],structure_judged=ctx['structure_judged_count'],
                  candidates=ctx['auction_candidate_count'],labels=ctx['states'],
                  selected=ctx['auction_rows'][:3],input='真实获取报价回放；历史日线重算使用当前池，不是当时实测名单')
        result.append(info)
        name='auction_'+at.strftime('%H%M')
        replay['generated_at']=acquisition['captured_at'];replay['history_reference']={'available_days':calendar[-20:]}
        tpl=(ROOT/'dashboard_template.html').read_text(encoding='utf-8')
        (ROOT/'output/playwright'/ (name+'.html')).write_text(tpl.replace('/*__DATA__*/null',json.dumps(replay,ensure_ascii=False,separators=(',',':'))),encoding='utf-8')
    (out/'auction_replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k not in ('selected','labels')} for r in result],ensure_ascii=False))

def refresh_template():
    """仅刷新回放页面外观，保持已验证的回放数据不变。"""
    tpl=(ROOT/'dashboard_template.html').read_text(encoding='utf-8')
    for minute in ('0915','0920','0926'):
        path=ROOT/'output/playwright'/('auction_'+minute+'.html')
        old=path.read_text(encoding='utf-8')
        snap,_=json.JSONDecoder().raw_decode(old.split('var DATA = ',1)[1])
        path.write_text(tpl.replace('/*__DATA__*/null',json.dumps(snap,ensure_ascii=False,separators=(',',':'))),encoding='utf-8')

if __name__=='__main__':
    refresh_template() if '--template-only' in sys.argv else run()
