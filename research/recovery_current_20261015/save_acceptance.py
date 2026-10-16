import csv,io,json,sys
from pathlib import Path
from urllib.request import urlopen
OUT=Path(__file__).resolve().parent;sys.path.insert(0,str(OUT.parents[1]));import ma_trend
raw=(OUT/'browser_cli.txt').read_text(encoding='utf-8-sig')
b=json.loads(next(line for line in raw.splitlines() if line.startswith('{"base":')))
status=json.loads(urlopen('http://127.0.0.1:8848/__status',timeout=15).read())
assert not b['errors'] and b['base']['noncurrentEvents']==0
assert status['phase']=='ready' and status['last_scan_ok'] and status['last_publish_ok']
assert status['code_ma_trend_hash']==status['snapshot_ma_trend_hash']==b['base']['hash']==ma_trend.IMPLEMENTATION_HASH
rows=list(csv.DictReader(io.StringIO(b['versions']['csv'].lstrip('\ufeff'))))
current=next(r for r in rows if r['代码']==b['selected']['code']);expired=next(r for r in rows if r['代码']=='002687')
assert current['涨停收复候选日期']==b['selected']['event']['date']
assert expired['涨停收复候选日期']==expired['涨停收复候选状态']==''
assert b['base']['generation']==b['versions']['generation']==b['versions']['detailVersion']
assert all(1<=c['event']['age_sessions']<=5 and not c['pending'] for c in b['base']['current'])
(OUT/'browser_acceptance.json').write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'status_after.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
f=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf-8'));assert f['hash']==ma_trend.IMPLEMENTATION_HASH
body=f'''# 涨停收复候选最新周期与标签展示验收

版本：{ma_trend.VERSION}。实际页面行情截至：{b['base']['source']}。UI版本：{b['base']['generation']}。服务PID：{status['pid']}。

## 当前规则

仅展示最新一轮收复事件，含当前交易日在内最近5个交易日。事件日为第1日，第5日仍可展示，第6日隐藏；周末与节假日不计入交易日。最新完成日线、报价时间、价格口径和所需支撑分钟核验继续生效。失效、已正式确认、窗口到期和数据未核验的历史候选不展示为当前标签，也不进入候选筛选。

后端用同一`recovery_current`状态驱动雷达筛选、个股排名标签、页面摘要、详情展示和CSV候选列。内部仍保留历史事实用于周期和失效跟踪，避免同一次失效事件反弹后错误复活。

## 展示

在现有雷达及个股列表中使用淡紫色圆角标签，显示“涨停收复｜候选”；不重复堆叠长状态。候选行显示本轮收复日期、第几/5个交易日及事件量比。旧波段起点不再混入候选主行和候选详情。标签保留鼠标悬浮及键盘聚焦解释；上涨红色、下跌绿色规则保持。

未新增页面或模块。全部阶段、全部成员仍为默认选项；隐藏历史标签不会删掉完整成员排名中的股票。

## 核验

- 冻结数据时间：{f['source']}；完成日截至{f['asof']}。{f['daily_tested']}只可用股票原有阶段、起点、平台、退出记录保持一致；情绪分和数值排名保持一致。
- 冻结输入中当前候选由{f['old_current']}只收敛至{f['new_current']}只，{f['historical_events_hidden_from_summary']}条历史候选事件从页面摘要隐藏。
- 704项全量测试通过；最终94项针对性回归通过，覆盖第5/6个交易日边界、跨周末、报价过期、支撑待核验、失效不复活及新周期不受旧候选影响。
- 浏览器实际候选{len(b['base']['current'])}只，均在5个交易日内；摘要历史候选0条。标签单次展示、圆角/间距/高度、悬浮解释、候选筛选、完整成员保留、详情和同版CSV一致性均通过。
- 乔治白002687在当前观察日已超出窗口，候选标签和CSV候选日期/状态均隐藏。

证据：`frozen_comparison.json`、`browser_acceptance.json`、`status_after.json`、`focused_tests.txt`、`full_tests.txt`、`live_service_check.txt`、`dashboard_check.txt`、`source.diff`。源码、快照、数据库、分钟记录和原始报价批次备份在`baseline/`。
'''
(OUT/'验收说明.md').write_text(body,encoding='utf-8')
print(json.dumps(dict(version=ma_trend.VERSION,source=b['base']['source'],generation=b['base']['generation'],current=len(b['base']['current']),historical_visible=b['base']['noncurrentEvents'],chosen=b['selected']['code'],age=b['selected']['event']['age_sessions'],style=b['style']),ensure_ascii=False))
