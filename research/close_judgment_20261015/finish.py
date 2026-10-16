import json,re,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent
r=json.loads((OUT/'release_acceptance.json').read_text(encoding='utf-8'))
raw=(OUT/'browser_acceptance.txt').read_text(encoding='utf-8');m=re.search(r'### Result\s*\n([^\n]+)',raw);assert m,'Browser acceptance missing'
b=json.loads(m[1]);assert b['generation']==r['status']['ui_generation'] and not b['errors']
focused=(OUT/'focused_tests.txt').read_text(encoding='utf-8');full=(OUT/'full_tests.txt').read_text(encoding='utf-8')
assert re.search(r'Ran \d+ tests.*?\n\s*OK',full,re.S) and re.search(r'Ran \d+ tests.*?\n\s*OK',focused,re.S)
fc=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf-8'))
for key,name in [('ms','market_strength'),('ma','ma_trend'),('emotion','emotion_relay')]:assert fc['hashes'][key]==r['status']['code_'+name+'_hash']
doc=f'''# 最终收盘判断漏洞修复

服务 PID {r['status']['pid']}，phase=ready；页面版本 `{r['status']['ui_generation']}`。
完成交易日 {r['close']['date']}；真实行情源时间截至 {r['source_at']}。

## 原因和修复

旧趋势报价校验仅接受15:00—15:02，供应商收盘后继续更新时间戳，造成已有最终完成日线却全池待核验。15:03边界采样只有1572/3120只通过旧校验，不到60%整批恢复门槛；后续批次全部被时间限制拒绝。旧均线还会用缺失的分钟过程覆盖收盘结果。

新增共享的closing_price核验，由趋势、均线、情绪共同使用：同交易日、可信原价报价与昨收语义、独立完成日线、经核验的价格尺度及开高低收逐项一致；报价日期、未来时间、真实成交、来源和价格冲突仍拒绝。保留真实源时间，不伪造15:00报价。报价采集早于本轮日线核验时，以实际日线核验完成时刻评估，源报价时间独立保留。

最终完成日线决定收盘均线阶段、支撑和日线底部反弹；不请求分钟过程，不让分钟缺失覆盖收盘结论。盘中15个交易分钟规则保留。收盘重放也不沿用盘中已退出或降级记录来覆盖新的最终日线结论。

已核验的同日收盘批次会保存；后续报价不可用时重新核验已有批次，重启可从原始采集档案恢复。保留整批覆盖门槛，不靠放宽阈值恢复结果。

全局页头改为显示正式收盘已核验、完成日线日期和真实源时间。增加服务验收断言：当日正式日线已就绪时，不允许趋势有效覆盖为零、均线全池待核验或仍依赖分钟过程。

## 实际结果

- 趋势有效 {r['market_coverage']['trend_valid']}/3120；价格活跃参考有效 {r['market_coverage']['emotion_valid']}/3120。
- 均线可核算 {3120-r['pending']}/3120；数据待核验 {r['pending']}只。
- 阶段有效观察：MA5 {r['ma_counts']['5']}，MA10 {r['ma_counts']['10']}，MA20 {r['ma_counts']['20']}。不为增加名单调整准入条件。
- 待核验原因：{json.dumps(r['pending_reasons'],ensure_ascii=False)}。
- 原始报价、历史日线、日线强度值、板块成员与指数历史未变；MA和强度全部数值参数未变，规则版本随修复更新。

## 验证

- {re.search(r'Ran (\d+) tests',focused).group(1)}项定向测试和{re.search(r'Ran (\d+) tests',full).group(1)}项全量隔离测试通过。
- frozen_inputs.json.gz保留修复前快照、原始采集及160日历史；frozen_comparison.json记录同一输入前后比较。baseline和source_changes.diff保留代码基线与可审阅改动。
- 浏览器实际验证雷达阶段及范围、剩余待核验原因、慈文传媒推进状态、皇台酒业近5日收复候选、中文输入法、标签解释、个股详情、CSV同版本、完整成员趋势排名、情绪涨停池与停牌核心、窄屏和全局收盘时间提示。页面错误为0。
- check_live_service.py、check_dashboard.py通过；后台、磁盘快照、HTTP summary/detail/export及页面数据版本一致。
- 逐股结果：收盘状态核对.csv；截图：output/playwright/closing-judgment-radar.png、closing-judgment-stock.png、closing-judgment-narrow.png。
'''
(OUT/'修复验收.md').write_text(doc,encoding='utf-8')
print(json.dumps(dict(generation=r['status']['ui_generation'],pid=r['status']['pid'],coverage=r['market_coverage'],ma_counts=r['ma_counts'],pending=r['pending'],source=r['source_at']),ensure_ascii=False))
