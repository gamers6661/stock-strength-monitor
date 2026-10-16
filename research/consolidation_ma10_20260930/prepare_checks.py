# -*- coding: utf-8 -*-
"""复用真实页面导出与午休输入验收，更新本轮的可见语义。"""
from pathlib import Path
folder=Path(__file__).resolve().parent
old=folder.parent/'consolidation_audit_20260930'
for name in ('collect_evidence.py','check_frontend.js','check_export.js','check_midday_export.py'):
    text=(old/name).read_text(encoding='utf-8')
    if name=='collect_evidence.py':
        text=text.replace("'config.py','trend_consolidation.py'","'config.py','consolidation_tracking.py','consolidation_rebound.py','test_consolidation_rebound.py','intraday.py','trend_consolidation.py'")
    if name=='check_frontend.js':
        text=text.replace("const functions=source('consolidationDisplay')", "const functions=source('consolidationPeriodText')+'\\n'+source('consolidationDisplay')")
        text=text.replace("shape:'横盘整理',location:","consolidation_start:'2026-09-23',consolidation_elapsed_days:4,consolidation_day_number:5,shape:'横盘整理',location:")
        text=text.replace("'已整理完毕转强 1 只'","'转强后跟踪 1 只'")
        text=text.replace("console.log(JSON.stringify", "check(()=>{let text=nodes['work-consolidation-list'].innerHTML;assert(text.includes('整理开始 2026-09-23'));assert(text.includes('已整理 4 个完成交易日'));assert(text.includes('今日第5日'));});\ncheck(()=>{sandbox.DATA.trend_consolidation.rows=[{...item,stage:'回踩反弹·MA10 · 分歧待修复'}];sandbox.renderConsolidationMonitor({});assert(nodes['work-consolidation-list'].innerHTML.includes('回踩反弹·MA10 · 分歧待修复'));});\nconsole.log(JSON.stringify")
    if name=='check_export.js':text=text.replace('consolidation_audit_20260930','consolidation_ma10_20260930')
    if name=='check_midday_export.py':
        text=text.replace('len(columns)==171','len(columns)==192')
        text=text.replace("r[eligibility]=='已完成整理，退出观察'","r[eligibility]=='已完成整理，进入转强跟踪'")
        text=text.replace("exported={r[code_field] for r in rows if r[eligibility]=='已完成整理，进入转强跟踪'}", "exported={r[code_field] for r in rows if r[eligibility]=='已完成整理，进入转强跟踪'}\nfor group in tc.GROUPS:\n    for item in snap['trend_consolidation'][group]:\n        if not item.get('completion_confirmed'):continue\n        record=next(r for r in rows if r[code_field]==item['code'])\n        assert record['历史转强确认']=='是' and record['整理状态']==item['stage']\n        assert record['MA10退出时间']==str(item.get('trend_exit_at') or '')")
    (folder/name).write_text(text,encoding='utf-8')
