"""保存实时数据改善、未补齐原因及正式日历证据。"""
from collections import Counter
import json
from pathlib import Path
import sys
import importlib.util

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import fund_history
import history_reference
spec=importlib.util.spec_from_file_location('context_audit',Path(__file__).with_name('audit.py'))
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

def run():
    out=Path(__file__).parent
    after=audit.inspect();(out/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
    before=json.loads((out/'before.json').read_text(encoding='utf-8'))
    snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
    rows=snap['stocks']+snap.get('coverage_catalog',[])
    history=fund_history.load()
    result=dict(before={k:before[k] for k in ('windows','score_history_gaps','fund_states','basis_reasons')},
                after={k:after[k] for k in ('windows','score_history_gaps','fund_states','basis_reasons')},
                snapshot_at=snap['generated_at'],context={k:v for k,v in snap['session_context'].items() if k!='auction_rows'},
                funds=snap['fund_confirmation'],fund_failure_reasons=dict(Counter(i.get('error') for i in history.values() if i.get('error'))),
                score_delta_sources={k:dict(Counter(r.get(k+'_source') or '主榜外不评分' for r in rows)) for k in ('strength_delta1','strength_delta5')},
                remaining=[{k:r.get(k) for k in ('code','name','trade_status','coverage_reason','daily_strength_status','fund_history_days','fund_history_reason','intraday_price_basis_reason')} for r in rows if r.get('fund3_yi') is None or r.get('intraday_price_basis_reason')],
                reference=snap.get('history_reference'),backup='backups/latest_before_session_context',
                calendar_evidence={'previous_completed_day':'2026-09-30','current_trading_day':'2026-10-08',
                  'holiday':'9月25日中秋休市；10月1日至7日国庆休市，不能将自然工作日补成交易日',
                  'sources':['https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml',
                             'https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml']})
    (out/'final_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('remaining','calendar_evidence','context')},ensure_ascii=False))

if __name__=='__main__':run()
