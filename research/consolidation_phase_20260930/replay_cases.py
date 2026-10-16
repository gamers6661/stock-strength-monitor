"""五个案例按完成日逐日截断回放：只验证形态覆盖及退出，不虚构盘中采样或交易收益。"""
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
import datafeed
import trend_consolidation as tc

folder=Path(__file__).resolve().parent
names={'002487':'大金重工','000710':'贝瑞基因','600059':'古越龙山','002388':'新亚制程','601811':'新华文轩'}
conn=datafeed.db()
calendar=[r[0] for r in conn.execute('SELECT DISTINCT date FROM kline ORDER BY date') if r[0]<='2026-09-30']
inputs={c:datafeed.load_kline(conn,'kline','code',c,limit=120) for c in names}
conn.close()
rows=[];differences=0;summary={}
for code,bars in inputs.items():
    for day in [d for d in calendar if d>='2026-08-01']:
        past=[b for b in bars if b['date']<=day]
        full=tc.daily_setup(bars,day,calendar)
        cut=tc.daily_setup(past,day,calendar)
        differences+=int(full!=cut)
        current=next((b for b in bars if b['date']==day),None)
        rows.append(dict(code=code,name=names[code],day=day,close=current.get('close') if current else None,
                         eligible=full['eligible'],phase=full.get('phase'),shape=full.get('shape'),
                         impulse5_pct=full.get('impulse5_pct'),impulse10_pct=full.get('impulse10_pct'),
                         setup_id=full.get('setup_id'),reason=full.get('reason'),
                         needs_repair_confirmation=full.get('needs_repair_confirmation'),
                         completed_at=full.get('completed_at')))
    recent=[r for r in rows if r['code']==code and r['day']>='2026-09-14']
    observed=[r['day'] for r in recent if r['eligible']]
    ended=[r['day'] for r in recent if r['phase']=='completed']
    assert observed, (code,'未覆盖近期整理形态，必须如实报告')
    assert recent[-1]['phase']=='completed' and recent[-1]['eligible'] is False
    summary[code]=dict(name=names[code],observed_days=observed,first_completed=ended[0],
                       latest_reason=recent[-1]['reason'],recent=recent)
assert differences==0
evidence=dict(version=tc.VERSION,parameters=config.TREND_CONSOLIDATION,
              source='本地已缓存完成日K线',calendar=calendar,summary=summary,rows=rows,
              future_isolation_differences=differences,
              note='日线资格/阶段回放，不代表当时已实时预警，不代表买卖收益；无历史逐轮报价的日期不能确认盘中初启动')
(folder/'case_inputs.json').write_text(json.dumps(inputs,ensure_ascii=False,indent=2),encoding='utf-8')
(folder/'case_replay.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 五个案例的整理阶段回放','',evidence['note'],'',
       '| 个股 | 9月14日以后符合整理日线资格的日期 | 首次归入已整理完毕转强 | 当前退出原因 |',
       '| --- | --- | --- | --- |']
for code,s in summary.items():lines.append('| '+s['name']+' '+code+' | '+ '、'.join(d[5:] for d in s['observed_days'])+' | '+s['first_completed']+' | '+s['latest_reason']+' |')
lines+=['','以下逐日记录包括不满足条件的日期；早期缺少40日窗口等原因保留在JSON内。']
for code,s in summary.items():
    lines+=['','## '+s['name'],'','| 日期 | 收盘价 | 阶段 | 形态或原因 |','| --- | ---: | --- | --- |']
    for r in s['recent']:lines.append(f"| {r['day']} | {r['close']} | {'整理资格通过' if r['eligible'] else '已整理完毕转强' if r['phase']=='completed' else '未入选'} | {r.get('reason') or r.get('shape')} |")
(folder/'五股逐日回放.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(dict(summary={c:{k:v for k,v in s.items() if k!='recent'} for c,s in summary.items()},future_isolation_differences=differences),ensure_ascii=False))
