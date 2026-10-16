import json
from pathlib import Path
OUT=Path(__file__).resolve().parent
r=json.loads((OUT/'close_acceptance.json').read_text(encoding='utf-8'));m=r['meta'];s=r['status'];t=m['timeline'][-1]
browser=(OUT/'browser_acceptance.txt').read_text(encoding='utf-8');b=json.loads(browser.split('### Result\n',1)[1].split('\n',1)[0]);assert b['base']['generation']==s['ui_generation'] and not b['errors']
text=f'''# 情绪周期与监管接续：完成记录

交付口径：2026年10月15日正式收盘。最近20个完成交易日为 **{m['history_from']}—{m['history_asof']}**；实际报价源截至 **{m['source_at']}**。报价源时间、完成交易日、计算及页面发布时间分别保存。

## 已完成

- 新华传媒保留10板周期高度与停牌核心身份，真实末次成交日10月12日、价格13.78元；停牌不算断板，不增加板数，不计入当日在板与晋级分母。当日在交易最高5板单列。
- 断板补涨、监管接续和停牌接续分别建节点，以节点当日首板确定批次；保留首板日、核心当时已知高度及公告公开时间，后续晋级继续跟踪，正式收盘断板退出当前名单。
- 慈文传媒10月9日首板，对应新华传媒10月8日晚严重异动公告后的首个可交易日，收盘5板，标为监管接续候选。新经典本日收盘断板，已退出该当前候选名单。
- 伴生按父周期分别记录。新华文轩与新华传媒有9月21、22、23、24日同步封板证据；龙版传媒较早6板于9月8日结束，单列为新华传媒之前的同题材前轮高标。龙版与慈文10月9日起的新一轮有伴生观察关系，不能把不同父周期合为一个标签结论。
- 历史停牌接口覆盖旧区间的问题，用正式停复牌公告补齐；未知缺失不填成未涨停。收盘后更新源时刻的报价，逐股对照完成日线及价格尺度，开高低收全部匹配后才采用，保留真实源时刻。
- 上证A股000002、深证A指399107的最新分类指数已核对，提供截至10月15日的3/10/30日滚动偏离参考。日线延迟时用同代码、同日、前收衔接及OHLC均通过的指数收盘报价补齐，保留实际源时间。
- 情绪页、完整板块成员排名、标签解释、中文输入法、红涨绿跌、个股20日依据和同版CSV导出通过浏览器核验。

## 覆盖与边界

沪深主板普通10%制度池3120只，非全市场。正式收盘有效情绪报价 {m['coverage']['valid_quotes']} 只；当天收盘/停牌事实可核验 {t['valid']}/{t['expected']}，其中全天停牌 {t['suspended']}只、收盘封板 {t['limit_count']}只、未核验 {t['unknown']}只。未核验不是下跌、未涨停或失败，不用于制造精确首板与连板结论。

焦点股票公告缓存覆盖 {m['cycles']['disclosure_coverage']['covered']}/{m['cycles']['disclosure_coverage']['expected']}。本轮有1条公告正文身份/文本核验缺口，原始错误保留于close_acceptance.json；不据此认定无新公告或补写停复牌区间。新华传媒等本轮关键节点公告正文已核对。

共用题材仅为关系线索，具体催化与因果尚未结构化确认；伴生及接续均为观察标签，不是补涨龙胜出认定。滚动偏离按市场交易日计算，**没有执行公告/复牌重置，也不自动计算“10日4次”正式异常次数**；不构成正式监管认定、停牌预测或可继续上涨额度。正式公告事实独立展示。

## 验证

- **52项专项检查、757项全量测试通过**。包括真实按分涨停价、源缺失、停牌链、公告可知时间、旧批次失效、已知停牌缺口、收盘后报价的独立日线核对、指数身份/日期/前收不符拒绝。
- 冻结输入比较：逐股原MA结果、原价格活跃/趋势数值、板块成员及指数模型保持不变。ma_trend.py、ma_trend_ui.js、board_stock_rank.py及原主扫描集成文件与备份逐字节相同。
- MA规则版本仍为ma-trend-2026-10-15.4，哈希仍为e41462e168eb78ee165013e68c4b3501502ceb3996c17813562999e61c2f2261。
- check_live_service.py、check_dashboard.py及正式收盘专项校验通过。全局旧盘中模块输出的valid_quotes=0与独立情绪收盘报价{m['coverage']['valid_quotes']}只分开；本轮没有修改旧模块的行情门槛或MA算法。
- 浏览器验证8种范围、中文组合输入、悬浮说明、20日详情与概况CSV、文化传媒124只完整成员以及后端一致的情绪顺序，页面脚本错误0。涨幅红色RGB(232,39,26)，跌幅绿色RGB(18,164,92)。
- 服务PID **{s['pid']}**，phase=ready；代码、磁盘快照、HTTP页面与详情/导出同版。UI版本 **{s['ui_generation']}**，情绪实现哈希 **{m['implementation_hash']}**。

## 可复核材料

- 规则、公开来源及检索记录：规则与资料核对.md。
- 最新收盘逐股20日记录：正式收盘逐股20日核算.csv，共62400条；逐日概况：正式收盘20日概况.csv。
- 状态、案例完整依据与参考数值：close_acceptance.json；浏览器：browser_acceptance.txt及output/playwright/emotion-cycle-*.png。
- 源码比较：source.diff、source_review.json；冻结输入：baseline目录、frozen_comparison.json；测试：focused_tests.txt、full_tests.txt、live_service.txt、dashboard_check.txt。
'''
(OUT/'验收说明.md').write_text(text,encoding='utf-8')
print('report',OUT/'验收说明.md','generation',s['ui_generation'])
