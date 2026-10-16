import csv
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
raw=(OUT/'browser_result.txt').read_text(encoding='utf-8-sig')
assert '### Result' in raw,raw[:400]
browser,_=json.JSONDecoder().raw_decode(raw.split('### Result',1)[1].lstrip())
(OUT/'browser.json').write_text(json.dumps(browser,ensure_ascii=False,indent=2),encoding='utf-8')
def read_csv(name):
    with (ROOT/'output/playwright'/name).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);rows=list(reader);return reader.fieldnames,rows
headers,rows=read_csv('layout-all.csv')
prior_headers,prior=read_csv('current-judgment-all.csv')
assert headers==prior_headers and rows==prior,'布局修改前后的导出内容有差异'
assert len(rows)==3120 and len(headers)==241
scope=json.loads((OUT/'scope.json').read_text(encoding='utf-8'))
scope['csv_exactly_unchanged']=True;scope['csv_rows']=len(rows);scope['csv_columns']=len(headers)
(OUT/'scope.json').write_text(json.dumps(scope,ensure_ascii=False,indent=2),encoding='utf-8')
report='''# 页面标签与布局优化验收

本轮只修改 dashboard_template.html，并重新生成 dashboard.html。后台73份Python源码、数据快照、160个非本轮展示函数、导出函数保持不变；新增辅助函数只负责标签、数值显示与注释交互。

首页：股票名称和报价单独一行；形态、观察状态和风险改为标签；进攻分、价格分、ATR距离或整理天数、历史量比、回撤独立排版；时间只保留一处。规则说明移到标签注释。

个股详情：将当前判断置于走势之前，以状态标签和四个指标呈现。整理观察单独显示四个历史指标；数据来源、整理确认过程、固定平台、日内采样及完整核验默认折叠，原有依据保留。

注释支持悬停、点击和键盘聚焦；点击标签不会误打开个股，Escape可关闭注释。颜色只表达已有形态与风险标记，没有新增评分、评级或筛选门槛。价格涨跌仍按原有红涨绿跌。

实际验证：进攻75只、整理21只，数量与顺序逐项一致；CSV3120行、241列，全部字段及值与修改前导出完全一致；个股列表、雷达、记录展开、标签注释均正常。390px窄屏下指标两列显示，无标签截断和内容横向溢出。check_dashboard.py及check_live_service.py通过。

效果截图：output/playwright/layout-overview.png、layout-shidai.png、layout-xinhua.png、layout-detail-decision.png、layout-detail-mobile.png。详细证据见browser.json和scope.json。

原模板备份在本目录dashboard_template.before.html，仅供恢复，不参与运行。
'''
(OUT/'验收记录.md').write_text(report,encoding='utf-8')
print(json.dumps(dict(csv_rows=len(rows),csv_columns=len(headers),csv_exactly_unchanged=True,counts=browser['counts'],scope=scope),ensure_ascii=False))
