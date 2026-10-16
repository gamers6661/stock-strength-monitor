"""用真实行情完成一次扫描，并断言已取消的资金接口没有任何调用。"""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
import datafeed
import scoring
import fund_history
import fund_confirmation
import make_dashboard
import report

started=time.monotonic()
mode=sys.argv[1] if len(sys.argv)>1 else 'close'
with config.pipeline_guard(), patch.object(datafeed,'fetch_em_fundflow_all_resilient',side_effect=AssertionError('资金全池接口仍被调用')) as em, \
     patch.object(datafeed,'fetch_sina_fundflow_all',side_effect=AssertionError('新浪资金接口仍被调用')) as sina, \
     patch.object(datafeed,'fetch_em_boards_resilient',side_effect=AssertionError('板块资金接口仍被调用')) as board, \
     patch.object(fund_history,'refresh',side_effect=AssertionError('历史资金补采仍被调用')) as history, \
     patch.object(fund_confirmation,'attach',side_effect=AssertionError('历史资金参考仍被调用')) as reference:
    scoring.run(mode=mode)
    snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
    rows=snap['stocks']+snap.get('coverage_catalog',[])
    assert not any(s.get('fund_today_yi') is not None or s.get('fund_positive_all') is not None for s in rows)
    assert all(s.get('live_attack_score') is None or s['live_attack_score']==s['live_attack_price_score'] for s in rows)
    assert all(s['factors']['rs']==s['score']==s['stock_strength_percentile']
               and s['factors']['sector']==s['industry_breadth'] for s in snap['stocks'])
    counts=dict(eastmoney=em.call_count,sina=sina.call_count,board_fund=board.call_count,
                history=history.call_count,reference=reference.call_count)
    assert all(v==0 for v in counts.values())
    make_dashboard.build()
    config.atomic_write_text(config.ROOT/'snapshot_report.md',report.build(snap))
    result=dict(asof=snap['strength_model']['asof'],count=snap['close_strong_board']['count'],
                quote_at=snap['quote_capture_at'],generated_at=snap['generated_at'],
                close_verified=snap['close_daily_verified_at'],fund_calls=counts,
                seconds=round(time.monotonic()-started,1))
    result['mode']=mode
    result['close_refresh_version']=snap['close_refresh_version']
    result['close_pending']=snap['close_strong_board'].get('today_pending')
    result['price_pipeline_locked']=True
    filename='runtime_quick_result.json' if mode=='quick' else 'runtime_result.json'
    config.atomic_write_text(Path(__file__).parent/filename,json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))
