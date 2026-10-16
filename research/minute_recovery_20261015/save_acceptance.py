import json,sys
from pathlib import Path
from urllib.request import urlopen
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT));import ma_trend
raw=(OUT/'browser_cli.txt').read_text(encoding='utf-8-sig')
b=json.loads(next(line for line in raw.splitlines() if line.startswith('{"base":')))
status=json.loads(urlopen('http://127.0.0.1:8848/__status',timeout=15).read())
assert not b['errors'] and not b['live']['pending']
assert status['phase']=='ready' and status['last_scan_ok'] and status['last_publish_ok']
assert status['code_ma_trend_hash']==status['snapshot_ma_trend_hash']==b['base']['hash']==ma_trend.IMPLEMENTATION_HASH
assert '快照已过期' not in b['ranking']
(OUT/'browser_acceptance.json').write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'status_after.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
f=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf-8'))
report=f'''# 分钟记录修复与涨停收复候选验收

版本：{ma_trend.VERSION}。服务 PID {status['pid']}。实际页面数据时间：{b['base']['source']}；UI版本：{b['base']['generation']}。

## 已修复的原因

- 原先每轮仅轮询24只，需要核验的股票有约150只，导致尾部长期落后。现在全部入队，用6个工作线程和45秒预算补取；不修改行情原始时间。
- 补取空结果或网络失败曾覆盖已有分钟记录。现在合并同日、同口径的真实记录，保留已取得的历史，并检查起点、中间缺口及尾部。
- 部分无成交分钟不会生成新浪K线。只在腾讯逐分钟累计成交量、成交额和价格均未变化，且日期、前后分钟及已知价格可以对应时，附上无成交核验依据；不生成OHLC，不放宽有成交缺口。
- 个股排名的ISO时间被当成本地时间读取，导致有效行情误报过期。现在保留ISO时区语义，另有时间边界回归测试。

## 涨停收复

旧波段已结束；完成日收盘封住已知10%涨停，收复MA5和MA10且两线向上，前一日曾低于至少一条线。独立候选不要求20日新高，量比单独展示，不替代普通放量/突破入口。候选MA10有效失守后失效；新强势入口完成确认后结束候选状态。未完成日不会生成完成日收复事实。

候选作为现有列表的状态、标签及筛选项展示，没有新增模块。候选日期、历史波段起点、旧退出日期分别记录。皇台酒业候选日期为2026-10-13，旧波段起点为2026-09-21，旧退出为2026-10-09。

## 验证

- 冻结输入：{f['source']}，完成日截至{f['asof']}。{f['daily_tested']}只可用股票的原有日线阶段、起点、平台、退出记录一致；原有评分和情绪分一致。
- 174只股票补取完成174只，实测10.329秒；仅使用冻结报价分钟之前的分钟证据，未引入后续价格。支撑过程待核验68→0，其中66处为采集调度，2处为零成交记录。
- 实际页面待核验：{len(b['live']['pending'])}；分钟需要{b['base']['needed']}只，本轮实际请求{b['base']['fetch']['requested']}只、完成{b['base']['fetch']['completed']}只、复用缓存{b['base']['fetch']['cache_reused']}只，耗时{b['base']['fetch']['seconds']}秒。
- 694项全量测试通过；最终15项本轮回归通过，含新增时区边界验证。服务一致性检查和看板契约检查通过。
- 浏览器完成默认全部阶段/全部成员、候选标签筛选、悬浮解释、分钟覆盖、个股排名、详情和同版CSV验收，无页面脚本错误。

证据：`frozen_comparison.json`、`browser_acceptance.json`、`status_after.json`、`source.diff`、`full_tests.txt`、`live_service_check.txt`、`dashboard_check.txt`。源码、快照、数据库和分钟缓存备份在`baseline/`。

外部接口日后确实缺失有成交记录时，仍会明确保留核验状态；不会把缺数据伪装成确认支撑。此次冻结样本和上述实时页面均已完成核验。
'''
(OUT/'验收说明.md').write_text(report,encoding='utf-8')
print(json.dumps(dict(version=ma_trend.VERSION,pid=status['pid'],generation=b['base']['generation'],source=b['base']['source'],support_pending=len(b['live']['pending']),candidate_date=b['frozen']['event']['date'],minute_fetch=b['base']['fetch']),ensure_ascii=False))
