import json,re
from pathlib import Path
out=Path(__file__).resolve().parent
r=json.loads((out/'release_acceptance.json').read_text(encoding='utf-8'));meta=r['meta'];status=r['status']
raw=(out/'browser_acceptance.txt').read_text(encoding='utf-8');match=re.search(r'### Result\s*\n([^\n]+)',raw);assert match,'Missing browser result'
b=json.loads(match[1]);assert b['generation']==status['ui_generation'] and not b['errors']
full=(out/'full_tests.txt').read_text(encoding='utf-8');focused=(out/'focused_tests.txt').read_text(encoding='utf-8')
assert re.search(r'Ran \d+ tests.*?\n\s*OK',full,re.S) and re.search(r'Ran \d+ tests.*?\n\s*OK',focused,re.S)
freeze=json.loads((out/'frozen_comparison.json').read_text(encoding='utf-8'));assert freeze['hash']==meta['implementation_hash']
doc=f'''# 情绪页涨停池、断板观察及晋级名单验收

完成版本：{meta['version']}；服务 PID {status['pid']}，phase=ready。
正式收盘日：{meta['history_asof']}；实际行情源时间：{meta['source_at']}。
UI generation：`{status['ui_generation']}`。
实现哈希：`{meta['implementation_hash']}`。

## 页面结果

- 情绪页移除板块／题材筛选及隐藏方向条件。板块／题材页和完整成员排名入口保留。
- 当日涨停池 {len(meta['lists']['sealed'])}只，封板明细核验 {meta['pools']['strength_coverage']}/{meta['pools']['strength_expected']}。仅原有沪深普通10%主板样本，不宣称全市场。
- 先按精确连板高度降序，再在每个板位中按炸板次数少、封单/成交额高、最后封板和首次封板早排列。显示同板位名次及原始值；缺失不填零、不冒充弱势名次。一字板独立提示成交受限。
- 断板观察池 {len(meta['lists']['broken'])}只：最近20交易日，原连板至少3板，跟踪最近一轮断板。展示原高度、事件日、断板前样本最高标身份、今日反馈、断板后累计、距末板涨幅、断板日高低点。
- 再封1/2板继续记录断板后反馈；新一轮正式达到3板才结束旧观察。盘中未封仅为分歧待收盘；停牌不算断板。复牌首日的有效报价同样适用待收盘观察；历史缺失不补成断板。
- “弱后转强观察”使用已核验断板日非正涨幅、今日涨幅转正、较开盘上涨≥3%、现价位于日内区间上部70%的条件。上涨未封、反弹、再封板、实际跌停和跌破断板日低点等分别显示。状态是事实观察，不认证唯一龙头。
- 每张晋级卡片可点击成功名单；名单数量严格等于统计分子。盘中写在板待确认，正式收盘写晋级成功；未知报价不算失败。
- 两个股票池各有独立搜索、输入法保护、CSV及个股详情。涨幅红、跌幅绿；新增标签有悬浮解释。长列表在卡片内滚动并固定表头。

## 数据依据

- 当日涨停明细：东方财富 getTopicZTPool，逐个核对请求日、供应商市场日、真实采集时间、独立核验价格及字段有效性。盘中明细与报价相差不超过120秒；收盘使用同交易日收盘后统计。
- 字段含义通过[东方财富涨停页面](https://quote.eastmoney.com/ztb/detail)的官方前端脚本核对：`fbt`首次封板、`lbt`最后封板、`zbc`炸板次数、`fund`封板资金、`amount`成交额。核对原件保存在 vendor_detail.js、vendor_page.html；原始应答在 eastmoney_limit_pool_raw.json。
- 连板高度沿用原价OHLC及参考前收交叉核验；供应商lbc只作原始记录，不覆盖本系统精确链。停牌、异动公告与监管接续逻辑保留。
- 封单可撤销；这里只作同板位证据排序，不计算连板成功概率。

## 验证证据

- 定向测试：{re.search(r'Ran (\d+) tests',focused).group(1)}项通过；全量隔离测试：{re.search(r'Ran (\d+) tests',full).group(1)}项通过。
- baseline保留修改前源文件与快照；frozen_inputs.json.gz冻结原始采集、完成日线及情绪证据。frozen_comparison.json证明：{'; '.join(freeze['unchanged'])}。
- 实际浏览器验收：涨停池全部板位过滤、两个搜索框中文输入法、断板事实、悬浮说明、全部晋级卡片的名单与分子一致、个股详情和CSV同版本、窄屏展示、红涨绿跌，页面错误为0。
- 服务、磁盘快照、HTTP summary/detail/export及页面版本一致；另见live_service.txt和dashboard_check.txt。
- 实际截图：output/playwright/emotion-pools-caps.png、emotion-pools-broken.png、emotion-pools-promotion.png、emotion-pools-narrow.png。
'''
(out/'验收说明.md').write_text(doc,encoding='utf-8')
print(json.dumps(dict(generation=status['ui_generation'],source=meta['source_at'],caps=b['caps'],broken=b['broken'],strength=b['strength'],promotion=b['promotion'],tests=re.search(r'Ran (\d+) tests',full).group(1),pid=status['pid']),ensure_ascii=False))
